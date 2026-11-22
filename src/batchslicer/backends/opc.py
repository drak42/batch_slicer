"""Read OrcaSlicer's packed preset files (``<vendor>.opc``) and unpack them as JSON.

OrcaSlicer 2.4 keeps each vendor's built-in presets in a ``<vendor>.opc`` file
in its settings folder, and from 2.5 it ships them only in that form. The
format is OrcaSlicer's own (``PresetCacheFormat.cpp`` in its source, format
version 2): a 20-byte header (magic, version, body size, CRC-32) and a body
written with the cereal binary archive, holding a dictionary of setting names
and types, the vendor's printer models, then every process, filament and
printer preset as its own settings plus the name of the preset it inherits
from. That is the same information as the JSON preset files older releases
shipped, so :func:`unpack` writes it back out in that JSON form, which the rest
of BatchSlicer (and the slicer's command line) reads.

Values are written as the text OrcaSlicer itself uses (``"30%"``, ``"0x0"``,
``"nil"``, lists for multi-value settings). This module only reads ``.opc``
files and writes JSON; it never changes the slicer's files.
"""

import json
import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from batchslicer.backends.presets import PresetError

_MAGIC = 0x4F52435A  # "ZCRO" on disk
_FORMAT_VERSION = 2
_HEADER = struct.Struct("<IIQI")
_KINDS = ("process", "filament", "machine")
"""The preset lists in the order OrcaSlicer writes them."""

# OrcaSlicer's ConfigOptionType values (Config.hpp).
_VECTOR = 0x4000
_FLOAT, _INT, _STRING, _PERCENT, _FLOAT_OR_PERCENT = 1, 2, 3, 4, 5
_POINT, _POINT3, _BOOL, _ENUM = 6, 7, 8, 9
_POINTS_GROUPS, _INTS_GROUPS = 10 | _VECTOR, 11 | _VECTOR

_INT_NIL = 2**31 - 1
_BOOL_NIL = 255
_ENUM_UNNAMED = 0

_PRINTER_MODEL_STRINGS_AFTER_LISTS = 9
"""bed_model ... hotend_model in VendorProfile::PrinterModel::serialize."""


@dataclass(frozen=True, slots=True)
class OpcPreset:
    """One built-in preset as stored: its own settings and what it inherits."""

    kind: str
    """``process``, ``filament`` or ``machine``."""

    name: str
    sub_path: str
    """Where the preset's JSON file lived in the vendor's folder, such as
    ``machine/fdm_machine_common.json``."""

    settings: dict[str, Any]
    inherits: str = ""
    instantiation: str = ""
    setting_id: str = ""
    filament_id: str = ""
    description: str = ""
    renamed_from: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OpcVendor:
    """Every built-in preset of one vendor."""

    name: str
    version: str
    presets: tuple[OpcPreset, ...] = field(default=())


def read_opc(path: Path) -> OpcVendor:
    """Return the vendor and presets in the ``.opc`` file at ``path``.

    Raises :class:`PresetError` if the file is not a format-2 preset file, is
    damaged, or cannot be read completely.
    """
    try:
        data = path.read_bytes()
    except OSError as error:
        raise PresetError(f"Cannot read {path}: {error}") from error
    if len(data) < _HEADER.size:
        raise PresetError(f"{path} is not an OrcaSlicer preset file.")
    magic, version, size, crc = _HEADER.unpack_from(data)
    body = data[_HEADER.size :]
    if magic != _MAGIC:
        raise PresetError(f"{path} is not an OrcaSlicer preset file.")
    if version != _FORMAT_VERSION:
        raise PresetError(
            f"{path} uses preset file format {version}; this BatchSlicer reads format "
            f"{_FORMAT_VERSION}. A newer BatchSlicer may be needed for this slicer version."
        )
    if size != len(body) or zlib.crc32(body) != crc:
        raise PresetError(f"{path} is damaged (its size or checksum does not match).")
    try:
        return _read_body(_Reader(body))
    except (struct.error, UnicodeDecodeError, ValueError, IndexError) as error:
        raise PresetError(f"Cannot read the presets in {path}: {error}") from error


def unpack(vendor: OpcVendor, target: Path) -> Path:
    """Write every preset of ``vendor`` as ``target/<vendor>/<sub_path>`` JSON and return that folder."""
    folder = target / vendor.name
    for preset in vendor.presets:
        destination = folder / _safe_relative(preset.sub_path, preset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(_as_json(preset), indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return folder


def _as_json(preset: OpcPreset) -> dict[str, Any]:
    """Return a preset the way OrcaSlicer's JSON preset files state it."""
    data: dict[str, Any] = {"type": preset.kind, "name": preset.name}
    if preset.inherits:
        data["inherits"] = preset.inherits
    data["from"] = "system"
    for key in ("instantiation", "setting_id", "filament_id", "description"):
        value = getattr(preset, key)
        if value:
            data[key] = value
    if preset.renamed_from:
        data["renamed_from"] = _string_list(preset.renamed_from)
    data.update(preset.settings)
    return data


def _string_list(values: tuple[str, ...]) -> str:
    """Return names as one text value, the way OrcaSlicer's JSON files hold ``renamed_from``.

    OrcaSlicer reads it with ``unescape_strings_cstyle``: ``;``-separated, each
    name in double quotes (with ``\\`` and ``"`` escaped) where needed.
    """
    def plain(value: str) -> bool:
        return bool(value) and value == value.strip() and not any(c in value for c in ';"\\\n\r\t')

    if len(values) == 1 and plain(values[0]):
        return values[0]
    return ";".join(
        '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        for value in values
    )


def _safe_relative(sub_path: str, preset: OpcPreset) -> PurePosixPath:
    """Return ``sub_path`` if it stays inside the vendor folder; refuse anything else."""
    path = PurePosixPath(sub_path.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or path.suffix != ".json":
        raise PresetError(f"Preset '{preset.name}' has an unexpected file path: {sub_path!r}")
    return path


class _Reader:
    """Read cereal binary-archive values (little-endian, 64-bit sizes)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.offset = 0

    @property
    def at_end(self) -> bool:
        return self.offset == len(self._data)

    def unpack(self, fmt: str) -> Any:
        value = struct.unpack_from("<" + fmt, self._data, self.offset)
        self.offset += struct.calcsize("<" + fmt)
        return value[0] if len(value) == 1 else value

    def size(self) -> int:
        size = int(self.unpack("Q"))
        if size > len(self._data) - self.offset:
            raise ValueError(f"a length of {size} runs past the end of the file")
        return size

    def raw(self, length: int) -> bytes:
        if length > len(self._data) - self.offset:
            raise ValueError("data runs past the end of the file")
        chunk = self._data[self.offset : self.offset + length]
        self.offset += length
        return chunk

    def string(self) -> str:
        return self.raw(self.size()).decode("utf-8")

    def strings(self) -> list[str]:
        return [self.string() for _ in range(self.size())]

    def array(self, fmt: str) -> list[Any]:
        return [self.unpack(fmt) for _ in range(self.size())]


def _read_body(reader: _Reader) -> OpcVendor:
    """Read the body that follows the header (``VendorCacheFile::save``)."""
    cache_version = reader.unpack("I")
    if cache_version != _FORMAT_VERSION:
        raise ValueError(f"unexpected body format {cache_version}")
    vendor, version = reader.string(), reader.string()
    keys = reader.strings()
    types = reader.array("H")
    enum_names = reader.strings()
    if len(keys) != len(types) or not enum_names or enum_names[0]:
        raise ValueError("the setting dictionary is inconsistent")
    _skip_vendor_profiles(reader)
    presets: list[OpcPreset] = []
    for kind in _KINDS:
        for _ in range(reader.unpack("I")):
            presets.append(_read_preset(reader, kind, keys, types, enum_names))
    reader.unpack("Q")  # parse errors counted when the file was written
    if not reader.at_end:
        raise ValueError("unexpected data after the presets")
    return OpcVendor(name=vendor, version=version, presets=tuple(presets))


def _skip_vendor_profiles(reader: _Reader) -> None:
    """Read past the vendor map (``VendorProfile::serialize``); BatchSlicer does not use it."""
    for _ in range(reader.size()):
        reader.string()  # map key
        for _ in range(5):  # name, id, config_version, config_update_url, changelog_url
            reader.string()
        for _ in range(reader.size()):  # printer models
            for _ in range(3):  # id, name, model_id
                reader.string()
            reader.unpack("B")  # technology
            reader.string()  # family
            reader.strings()  # variants (each just a name)
            reader.strings()  # default_materials
            reader.strings()  # not_support_bed_types
            for _ in range(_PRINTER_MODEL_STRINGS_AFTER_LISTS):
                reader.string()
        reader.strings()  # default_filaments
        reader.strings()  # default_sla_materials


def _read_preset(
    reader: _Reader,
    kind: str,
    keys: list[str],
    types: list[int],
    enum_names: list[str],
) -> OpcPreset:
    """Read one preset (``visit_entry``): name, path, settings, then its metadata."""
    name, sub_path = reader.string(), reader.string()
    settings: dict[str, Any] = {}
    for _ in range(reader.unpack("I")):
        index = reader.unpack("H")
        if index >= len(keys):
            raise ValueError(f"setting index {index} is past the end of the dictionary")
        settings[keys[index]] = _read_value(reader, types[index], enum_names)
    inherits = reader.string()
    reader.strings()  # includes: not used by built-in presets so far
    description, instantiation, setting_id, filament_id = (reader.string() for _ in range(4))
    renamed_from = tuple(reader.strings())
    return OpcPreset(
        kind=kind,
        name=name,
        sub_path=sub_path,
        settings=settings,
        inherits=inherits,
        instantiation=instantiation,
        setting_id=setting_id,
        filament_id=filament_id,
        description=description,
        renamed_from=renamed_from,
    )


def _read_value(reader: _Reader, kind: int, enum_names: list[str]) -> Any:
    """Read one setting of OrcaSlicer type ``kind`` and return it as OrcaSlicer's text."""
    if kind in (_ENUM, _ENUM | _VECTOR):
        values = []
        for _ in range(reader.unpack("I")):
            index = reader.unpack("H")
            if index == _ENUM_UNNAMED:
                raw = reader.unpack("i")
                values.append("nil" if raw == _INT_NIL else str(raw))
            elif index < len(enum_names):
                values.append(enum_names[index])
            else:
                raise ValueError(f"enum index {index} is past the end of the dictionary")
        if kind == _ENUM:
            if len(values) != 1:
                raise ValueError("a single-choice setting holds more than one value")
            return values[0]
        return values
    if kind == _FLOAT:
        return _number(reader.unpack("d"))
    if kind == _PERCENT:
        return _number(reader.unpack("d"), percent=True)
    if kind in (_FLOAT | _VECTOR, _PERCENT | _VECTOR):
        return [_number(value, percent=kind == _PERCENT | _VECTOR) for value in reader.array("d")]
    if kind == _INT:
        return str(reader.unpack("i"))
    if kind == _INT | _VECTOR:
        return ["nil" if value == _INT_NIL else str(value) for value in reader.array("i")]
    if kind == _STRING:
        return reader.string()
    if kind == _STRING | _VECTOR:
        return reader.strings()
    if kind == _FLOAT_OR_PERCENT:
        return _float_or_percent(reader)
    if kind == _FLOAT_OR_PERCENT | _VECTOR:
        return [_float_or_percent(reader) for _ in range(reader.size())]
    if kind == _POINT:
        return ",".join(_number(value) for value in reader.unpack("dd"))
    if kind == _POINT | _VECTOR:
        return [_point(reader) for _ in range(reader.size())]
    if kind == _POINT3:
        return ",".join(_number(value) for value in reader.unpack("ddd"))
    if kind == _BOOL:
        return "1" if reader.unpack("B") else "0"
    if kind == _BOOL | _VECTOR:
        return ["nil" if byte == _BOOL_NIL else ("1" if byte else "0") for byte in reader.raw(reader.size())]
    if kind == _POINTS_GROUPS:
        return [",".join(_point(reader) for _ in range(reader.size())) for _ in range(reader.size())]
    if kind == _INTS_GROUPS:
        return [",".join(str(value) for value in reader.array("i")) for _ in range(reader.size())]
    raise ValueError(f"unknown setting type {kind:#x}")


def _float_or_percent(reader: _Reader) -> str:
    value, percent = reader.unpack("d?")
    return _number(value, percent=percent)


def _point(reader: _Reader) -> str:
    x, y = reader.unpack("dd")
    return f"{_number(x)}x{_number(y)}"


def _number(value: float, *, percent: bool = False) -> str:
    """Return a number as OrcaSlicer writes it: no trailing ``.0``, ``nil`` for unset."""
    if math.isnan(value):
        return "nil"
    text = repr(value)
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}%" if percent else text
