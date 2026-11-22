"""Add preview pictures to G-code, drawn from the G-code itself.

Slicers draw the preview pictures printers show on their screens only in
their windows; G-code sliced from the command line has none. This module
draws them from the toolpaths in the G-code: every extruding move of the
model (walls, surfaces, bridges; not skirt, brim, support, purge lines or
hidden infill) is seen from the front at an angle, shaded, and coloured with
the filament colour. Because the picture comes from the G-code, it shows the
part exactly as it will print, including auto-orient and each plate of a
project. The sizes are the ones the printer preset asks for
(``; thumbnails = 300x300/PNG, 96x96/PNG``), written as PNG in the block
format OrcaSlicer, PrusaSlicer and Creality Print use, just after the header.
Only the Python standard library is used.
"""

import base64
import math
import os
import re
import struct
import tempfile
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SIZES: tuple[tuple[int, int], ...] = ((300, 300), (96, 96))
"""Sizes used when the G-code does not say which the printer wants."""

_MAX_SIDE = 1024
_TAIL_BYTES = 512 * 1024
_LINE_WIDTH = 78
"""Base64 characters per line (80 with the leading ``; ``), as slicers write them."""

_HIDDEN_FEATURES = frozenset(
    name.casefold()
    for name in (
        "Custom", "Skirt", "Brim", "Skirt/Brim", "Support", "Support interface",
        "Support transition", "Support material", "Support material interface",
        "Prime tower", "Wipe tower", "Sparse infill", "Internal solid infill",
        "Internal infill", "Solid infill", "Internal Bridge", "Wipe",
    )
)
"""Features left out of the picture: not part of the model, or hidden inside it."""

_SIZES_PATTERN = re.compile(r"^; thumbnails = (.*)$", re.MULTILINE)
_COLOUR_PATTERN = re.compile(r"^; (?:filament_colour|extruder_colour) = (.*)$", re.MULTILINE)
_SIZE_PATTERN = re.compile(r"^\s*(\d+)\s*x\s*(\d+)\s*(?:/\s*(\w+))?\s*$", re.IGNORECASE)

_AZIMUTH = math.radians(35.0)
_ELEVATION = math.radians(38.0)
_LIGHT = (-0.45, -0.55, 0.70)
"""Light direction in picture space (x right, y down, towards the viewer)."""

_DEFAULT_COLOUR = (0x9A, 0x9F, 0xA6)

Segment = tuple[float, float, float, float, float]
"""An extruding move: ``(x0, y0, x1, y1, z)`` in millimetres."""


class ThumbnailError(Exception):
    """Raised when preview pictures cannot be added to a G-code file."""


@dataclass(frozen=True, slots=True)
class ThumbnailResult:
    """What was done to one G-code file."""

    added: tuple[tuple[int, int], ...] = ()
    """The sizes of the pictures added; empty when none were."""

    reason: str = ""
    """Why no pictures were added, when none were."""


def add_thumbnails(path: Path, sizes: Sequence[tuple[int, int]] | None = None) -> ThumbnailResult:
    """Draw preview pictures for the G-code at ``path`` and insert them into it.

    ``sizes`` defaults to the PNG sizes the G-code's own settings ask for, or
    :data:`DEFAULT_SIZES`. A file that already has pictures, or whose printer
    asks for none or only for formats other than PNG, is left unchanged. The
    file is replaced in one step, so it is never left half-written.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as error:
        raise ThumbnailError(f"Cannot read {path}: {error}") from error
    if "; thumbnail begin" in text[: 4 * 1024 * 1024]:
        return ThumbnailResult(reason="already has preview pictures")

    tail = text[-_TAIL_BYTES:]
    wanted = list(sizes) if sizes is not None else _wanted_sizes(tail)
    if not wanted:
        return ThumbnailResult(reason="the printer preset asks for no PNG preview pictures")
    segments = list(extrusions(text.splitlines()))
    if not segments:
        return ThumbnailResult(reason="no model toolpaths found")
    colour = _filament_colour(tail)
    blocks = "".join(
        _thumbnail_block(width, height, render_png(segments, width, height, colour))
        for width, height in wanted
    )
    _write_with_block(path, text, blocks)
    return ThumbnailResult(added=tuple(wanted))


def extrusions(lines: Iterable[str]) -> Iterable[Segment]:
    """Yield the extruding moves of the model in G-code ``lines``.

    Moves are absolute (``G90``) unless ``G91`` is given; extrusion may be
    relative (``M83``) or absolute (``M82``, with ``G92`` resets). Arcs
    (``G2``/``G3``) are followed in short straight pieces. Moves before the
    first feature marker (``;TYPE:`` or ``; FEATURE:``), such as a purge line,
    and features in :data:`_HIDDEN_FEATURES` are skipped.
    """
    x = y = z = e = 0.0
    relative_xyz = False
    relative_e = False
    shown = False
    for line in lines:
        if not line:
            continue
        first = line[0]
        if first == ";":
            if line.startswith(";TYPE:"):
                shown = line[6:].strip().casefold() not in _HIDDEN_FEATURES
            elif line.startswith("; FEATURE:"):
                shown = line[10:].strip().casefold() not in _HIDDEN_FEATURES
            continue
        if first not in "GM":
            continue
        code, _, rest = line.partition(";")[0].partition(" ")
        code = code.strip()
        if code in ("G1", "G0", "G2", "G3"):
            words = _words(rest)
            nx = words.get("X")
            ny = words.get("Y")
            nz = words.get("Z")
            ne = words.get("E")
            if relative_xyz:
                nx = x + nx if nx is not None else x
                ny = y + ny if ny is not None else y
                nz = z + nz if nz is not None else z
            else:
                nx = x if nx is None else nx
                ny = y if ny is None else ny
                nz = z if nz is None else nz
            extruding = False
            if ne is not None:
                if relative_e:
                    extruding = ne > 0
                else:
                    extruding = ne > e
                    e = ne
            if extruding and shown and code != "G0":
                if code == "G1":
                    if nx != x or ny != y:
                        yield (x, y, nx, ny, nz)
                else:
                    yield from _arc(x, y, nx, ny, nz, words, clockwise=code == "G2")
            x, y, z = nx, ny, nz
        elif code == "G90":
            relative_xyz = False
        elif code == "G91":
            relative_xyz = True
        elif code == "M82":
            relative_e = False
        elif code == "M83":
            relative_e = True
        elif code == "G92":
            words = _words(rest)
            e = words.get("E", e)


def render_png(
    segments: Sequence[Segment],
    width: int,
    height: int,
    colour: tuple[int, int, int] = _DEFAULT_COLOUR,
) -> bytes:
    """Return a PNG picture of ``segments``, ``width`` by ``height``, transparent around the part."""
    pixels = render(segments, width, height, colour)
    return encode_png(pixels, width, height)


def render(
    segments: Sequence[Segment],
    width: int,
    height: int,
    colour: tuple[int, int, int] = _DEFAULT_COLOUR,
) -> bytearray:
    """Return RGBA pixels (rows top to bottom) of ``segments`` seen from the front at an angle."""
    if not (0 < width <= _MAX_SIDE and 0 < height <= _MAX_SIDE):
        raise ThumbnailError(f"Unsupported picture size {width}x{height}")
    cos_a, sin_a = math.cos(_AZIMUTH), math.sin(_AZIMUTH)
    cos_e, sin_e = math.cos(_ELEVATION), math.sin(_ELEVATION)

    def project(px: float, py: float, pz: float) -> tuple[float, float, float]:
        across = px * cos_a + py * sin_a
        back = -px * sin_a + py * cos_a
        up = pz * cos_e + back * sin_e
        depth = back * cos_e - pz * sin_e
        return across, up, depth

    # Fit the part (all segment ends) into the picture with a small margin.
    xs: list[float] = []
    ys: list[float] = []
    for x0, y0, x1, y1, z in segments:
        for px, py in ((x0, y0), (x1, y1)):
            across, up, _ = project(px, py, z)
            xs.append(across)
            ys.append(up)
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    margin = 0.06
    scale = min(width * (1 - 2 * margin) / span_x, height * (1 - 2 * margin) / span_y)
    offset_x = (width - span_x * scale) / 2 - min(xs) * scale
    offset_y = (height - span_y * scale) / 2 + max(ys) * scale

    inf = math.inf
    depth_buffer = [inf] * (width * height)
    radius = 1 if scale * 0.45 >= 1.6 else 0
    step = 0.7 / scale  # millimetres between samples: under one pixel
    for x0, y0, x1, y1, z in segments:
        length = math.hypot(x1 - x0, y1 - y0)
        count = max(1, int(length / step))
        a0, u0, d0 = project(x0, y0, z)
        a1, u1, d1 = project(x1, y1, z)
        sx0 = a0 * scale + offset_x
        sy0 = offset_y - u0 * scale
        dx = (a1 - a0) * scale / count
        dy = -(u1 - u0) * scale / count
        dd = (d1 - d0) / count
        for i in range(count + 1):
            px = int(sx0 + dx * i)
            py = int(sy0 + dy * i)
            depth = d0 + dd * i
            if radius:
                for qy in (py, py + 1):
                    if 0 <= qy < height:
                        row = qy * width
                        for qx in (px, px + 1):
                            if 0 <= qx < width and depth < depth_buffer[row + qx]:
                                depth_buffer[row + qx] = depth
            elif 0 <= px < width and 0 <= py < height:
                index = py * width + px
                if depth < depth_buffer[index]:
                    depth_buffer[index] = depth

    _fill_pinholes(depth_buffer, width, height)
    return _shade(depth_buffer, width, height, scale, colour)


def encode_png(pixels: bytes | bytearray, width: int, height: int) -> bytes:
    """Return RGBA ``pixels`` (8 bits per channel, rows top to bottom) as PNG file bytes."""
    stride = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # no filter
        raw += pixels[row * stride : (row + 1) * stride]

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _words(text: str) -> dict[str, float]:
    """Return the letter-number words of a G-code line, such as ``X1.5 E.02``."""
    words: dict[str, float] = {}
    for word in text.split():
        if len(word) > 1:
            try:
                words[word[0].upper()] = float(word[1:])
            except ValueError:
                continue
    return words


def _arc(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    z: float,
    words: dict[str, float],
    *,
    clockwise: bool,
) -> Iterable[Segment]:
    """Yield an arc move (centre given by ``I``/``J`` from its start) as short straight pieces."""
    cx = x0 + words.get("I", 0.0)
    cy = y0 + words.get("J", 0.0)
    radius = math.hypot(x0 - cx, y0 - cy)
    if radius < 1e-6:
        yield (x0, y0, x1, y1, z)
        return
    start = math.atan2(y0 - cy, x0 - cx)
    end = math.atan2(y1 - cy, x1 - cx)
    sweep = end - start
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    pieces = max(2, int(abs(sweep) / math.radians(15)))
    px, py = x0, y0
    for i in range(1, pieces + 1):
        angle = start + sweep * i / pieces
        nx, ny = (x1, y1) if i == pieces else (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        yield (px, py, nx, ny, z)
        px, py = nx, ny


def _fill_pinholes(depth: list[float], width: int, height: int) -> None:
    """Fill empty pixels surrounded by the part (gaps between toolpaths) with their neighbours."""
    inf = math.inf
    holes = []
    for py in range(1, height - 1):
        row = py * width
        for px in range(1, width - 1):
            index = row + px
            if depth[index] != inf:
                continue
            around = [
                value
                for value in (
                    depth[index - 1], depth[index + 1], depth[index - width], depth[index + width],
                    depth[index - width - 1], depth[index - width + 1],
                    depth[index + width - 1], depth[index + width + 1],
                )
                if value != inf
            ]
            if len(around) >= 5:
                holes.append((index, sum(around) / len(around)))
    for index, value in holes:
        depth[index] = value


def _shade(
    depth: list[float],
    width: int,
    height: int,
    scale: float,
    colour: tuple[int, int, int],
) -> bytearray:
    """Return RGBA pixels lit from the upper left, using surface directions from the depths."""
    inf = math.inf
    lx, ly, lz = _LIGHT
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    red, green, blue = colour
    # Dark filaments are lifted so their shape still shows.
    brightness = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    lift = max(0.0, 0.35 - brightness) * 255
    limit = 6.0  # steepest slope used for shading; beyond it is an edge
    pixels = bytearray(width * height * 4)
    for py in range(height):
        row = py * width
        for px in range(width):
            index = row + px
            here = depth[index]
            if here == inf:
                continue
            left = depth[index - 1] if px > 0 else inf
            right = depth[index + 1] if px < width - 1 else inf
            up = depth[index - width] if py > 0 else inf
            down = depth[index + width] if py < height - 1 else inf
            gx = _slope(left, here, right) * scale
            gy = _slope(up, here, down) * scale
            gx = max(-limit, min(limit, gx))
            gy = max(-limit, min(limit, gy))
            # The surface faces the viewer (z) tilted by the depth slopes.
            nx, ny, nz = -gx, -gy, 1.0
            length = math.sqrt(nx * nx + ny * ny + 1.0)
            diffuse = max(0.0, (nx * lx + ny * ly + nz * lz) / length)
            light = 0.35 + 0.65 * diffuse
            highlight = diffuse ** 12 * 60
            out = index * 4
            pixels[out] = min(255, int((red + lift) * light + highlight))
            pixels[out + 1] = min(255, int((green + lift) * light + highlight))
            pixels[out + 2] = min(255, int((blue + lift) * light + highlight))
            pixels[out + 3] = 255
    return pixels


def _slope(before: float, here: float, after: float) -> float:
    """Return the change in depth per pixel, using the neighbours that are part of the picture."""
    inf = math.inf
    if before != inf and after != inf:
        return (after - before) / 2
    if after != inf:
        return after - here
    if before != inf:
        return here - before
    return 0.0


def _wanted_sizes(text: str) -> list[tuple[int, int]]:
    """Return the PNG sizes the G-code's settings ask for, largest first.

    No ``thumbnails`` setting gives :data:`DEFAULT_SIZES`; an empty one, or one
    naming only other formats (JPG, QOI, ...), gives none.
    """
    match = _SIZES_PATTERN.search(text)
    if match is None:
        return list(DEFAULT_SIZES)
    sizes = []
    for item in match.group(1).split(","):
        size = _SIZE_PATTERN.match(item)
        if size is None:
            continue
        kind = (size.group(3) or "PNG").upper()
        width, height = int(size.group(1)), int(size.group(2))
        if kind == "PNG" and 0 < width <= _MAX_SIDE and 0 < height <= _MAX_SIDE:
            sizes.append((width, height))
    return sorted(set(sizes), key=lambda item: -item[0] * item[1])


def _filament_colour(text: str) -> tuple[int, int, int]:
    """Return the first filament's colour from the G-code's settings, or a neutral grey."""
    for match in _COLOUR_PATTERN.finditer(text):
        first = match.group(1).split(";")[0].strip().strip('"').lstrip("#")
        if re.fullmatch(r"[0-9A-Fa-f]{6}", first):
            return int(first[0:2], 16), int(first[2:4], 16), int(first[4:6], 16)
    return _DEFAULT_COLOUR


def _thumbnail_block(width: int, height: int, png: bytes) -> str:
    """Return one picture as a G-code comment block."""
    encoded = base64.b64encode(png).decode("ascii")
    lines = [encoded[start : start + _LINE_WIDTH] for start in range(0, len(encoded), _LINE_WIDTH)]
    return (
        "; THUMBNAIL_BLOCK_START\n"
        ";\n"
        f"; thumbnail begin {width}x{height} {len(encoded)}\n"
        + "".join(f"; {line}\n" for line in lines)
        + "; thumbnail end\n"
        "; THUMBNAIL_BLOCK_END\n"
        "\n"
    )


def _write_with_block(path: Path, text: str, blocks: str) -> None:
    """Write ``text`` with ``blocks`` after its first header block (or at the start)."""
    marker = "; HEADER_BLOCK_END\n"
    position = text.find(marker, 0, 64 * 1024)
    cut = position + len(marker) if position >= 0 else 0
    joiner = "\n" if cut else ""
    new_text = text[:cut] + joiner + blocks + text[cut:]
    temporary: Path | None = None
    try:
        mode = path.stat().st_mode & 0o777
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            errors="surrogateescape",
            newline="",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(new_text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ThumbnailError(f"Cannot write {path}: {error}") from error
