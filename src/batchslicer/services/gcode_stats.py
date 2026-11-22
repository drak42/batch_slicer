"""Read the print time and filament use a slicer wrote into a G-code file.

OrcaSlicer, Creality Print and Bambu Studio write these as comments, for
example ``; estimated printing time (normal mode) = 1h 2m 3s`` and
``; total filament used [g] = 7.41``, near the end of the file (Bambu Studio
also near the start). A multi-material print also gives the grams of each
filament (``; filament used [g] = 13.78, 0.39``) and the number of filament
changes (``; total filament change = 36``). Only the start and end of the file are read, so large
files stay quick. Values that are missing are left as ``None``. This module
does not run slicers or change files.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_HEAD_BYTES = 64 * 1024
_TAIL_BYTES = 256 * 1024

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([dhms])")
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}

# Each statistic is (comment name, ...) in order of preference.
_TIME_NAMES = ("estimated printing time (normal mode)", "total estimated time")
_GRAMS_NAMES = ("total filament used [g]", "total filament weight [g]", "filament used [g]")
_LENGTH_NAMES = ("total filament length [mm]", "filament used [mm]")
_COST_NAMES = ("total filament cost", "filament cost")
_EACH_GRAMS_NAMES = ("filament used [g]", "total filament weight [g]")
_CHANGES_NAMES = ("total filament change", "total filament changes")


@dataclass(frozen=True, slots=True)
class GcodeStats:
    """What a G-code file says printing it will take."""

    print_seconds: float | None = None
    filament_grams: float | None = None
    filament_millimetres: float | None = None
    filament_cost: float | None = None
    grams_per_filament: tuple[float, ...] = ()
    """Grams of each filament slot, in slot order; empty when not given."""

    filament_changes: int | None = None
    """How many times the printer changes filament (multi-material prints)."""

    def __add__(self, other: "GcodeStats") -> "GcodeStats":
        """Return the totals of two files (for example the plates of one project)."""
        size = max(len(self.grams_per_filament), len(other.grams_per_filament))
        mine = self.grams_per_filament + (0.0,) * (size - len(self.grams_per_filament))
        theirs = other.grams_per_filament + (0.0,) * (size - len(other.grams_per_filament))
        changes = _add(self.filament_changes, other.filament_changes)
        return GcodeStats(
            _add(self.print_seconds, other.print_seconds),
            _add(self.filament_grams, other.filament_grams),
            _add(self.filament_millimetres, other.filament_millimetres),
            _add(self.filament_cost, other.filament_cost),
            tuple(a + b for a, b in zip(mine, theirs, strict=True)),
            int(changes) if changes is not None else None,
        )

    def used_filaments(self) -> tuple[tuple[int, float], ...]:
        """Return ``(slot number from 1, grams)`` for each filament slot that is used."""
        return tuple(
            (number, grams)
            for number, grams in enumerate(self.grams_per_filament, start=1)
            if grams > 0
        )


def read_gcode_stats(path: Path) -> GcodeStats:
    """Return the statistics found in the G-code file at ``path``.

    A file that cannot be read gives empty statistics rather than an error,
    since the G-code itself is still usable.
    """
    try:
        text = _read_ends(path)
    except OSError:
        return GcodeStats()
    values = _comment_values(text)
    duration = _first(values, _TIME_NAMES)
    changes = _number(_first(values, _CHANGES_NAMES))
    return GcodeStats(
        print_seconds=parse_duration(duration) if duration else None,
        filament_grams=_number(_first(values, _GRAMS_NAMES)),
        filament_millimetres=_number(_first(values, _LENGTH_NAMES)),
        filament_cost=_number(_first(values, _COST_NAMES)),
        grams_per_filament=_numbers(_first(values, _EACH_GRAMS_NAMES)),
        filament_changes=int(changes) if changes is not None else None,
    )


def total_stats(paths: Iterable[Path]) -> GcodeStats:
    """Return the combined statistics of several G-code files."""
    total = GcodeStats()
    for path in paths:
        total = total + read_gcode_stats(path)
    return total


def parse_duration(text: str) -> float | None:
    """Return a slicer duration such as ``1d 2h 3m 4s`` in seconds, or None."""
    parts = _DURATION_PART.findall(text)
    if not parts:
        return None
    return sum(float(amount) * _UNIT_SECONDS[unit] for amount, unit in parts)


def format_duration(seconds: float) -> str:
    """Return ``seconds`` as a short duration such as ``2d 3h 4m``."""
    minutes = round(seconds / 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = [f"{days}d"] if days else []
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _read_ends(path: Path) -> str:
    """Return the start and end of the file as text (all of it if small)."""
    with path.open("rb") as file:
        size = file.seek(0, 2)
        file.seek(0)
        if size <= _HEAD_BYTES + _TAIL_BYTES:
            data = file.read()
        else:
            head = file.read(_HEAD_BYTES)
            file.seek(size - _TAIL_BYTES)
            data = head + b"\n" + file.read()
    return data.decode("utf-8", errors="replace")


def _comment_values(text: str) -> dict[str, str]:
    """Return ``name -> value`` for comment lines like ``; name = value`` or ``; name: value``.

    Bambu Studio puts several on one line separated by ``;``. The first
    occurrence of a name wins.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith(";"):
            continue
        for part in line.split(";"):
            name, separator, value = _split(part)
            if separator and name and name not in values:
                values[name] = value
    return values


def _split(part: str) -> tuple[str, str, str]:
    """Split ``name = value`` or ``name : value``, whichever separator comes first."""
    positions = [index for index in (part.find("="), part.find(":")) if index >= 0]
    if not positions:
        return "", "", ""
    index = min(positions)
    return part[:index].strip().casefold(), part[index], part[index + 1 :].strip()


def _first(values: dict[str, str], names: tuple[str, ...]) -> str | None:
    """Return the value of the first of ``names`` present."""
    for name in names:
        if name in values:
            return values[name]
    return None


def _number(value: str | None) -> float | None:
    """Return the sum of the comma-separated numbers in ``value`` (one per filament)."""
    if value is None:
        return None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", value)
    return sum(float(number) for number in numbers) if numbers else None


def _numbers(value: str | None) -> tuple[float, ...]:
    """Return the comma-separated numbers in ``value`` (one per filament), or ``()``."""
    if value is None:
        return ()
    return tuple(float(number) for number in re.findall(r"-?\d+(?:\.\d+)?", value))


def _add(first: float | None, second: float | None) -> float | None:
    """Add two optional values; a missing value counts as unknown only if both are."""
    if first is None:
        return second
    if second is None:
        return first
    return first + second
