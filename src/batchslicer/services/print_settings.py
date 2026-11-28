"""Write ``print-settings.txt``: what a run's G-code was sliced for, in plain words.

The file sits in the run's result folder, next to the ``presets`` folder that
holds the complete preset files. It names the slicer, printer, filament(s) and
process preset, lists the main settings those presets apply (layer height,
walls, infill, speeds, temperatures...), and, for a preset of the user's own,
what it changes compared with the preset it is based on. Values are read from
the complete preset files written for the slicer, so the summary matches what
was actually used. This module only writes the summary; it does not choose or
resolve presets.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PRINT_SETTINGS = "print-settings.txt"
"""The summary's file name in a result folder."""

_ON_OFF = "on/off"
"""Marks a setting stored as 0 or 1, shown as off or on."""

_PRINTER_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("nozzle_diameter", "Nozzle diameter", "mm"),
    ("printable_height", "Printable height", "mm"),
)

_PROCESS_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("layer_height", "Layer height", "mm"),
    ("initial_layer_print_height", "First layer height", "mm"),
    ("wall_loops", "Walls", ""),
    ("wall_generator", "Wall generator", ""),
    ("top_shell_layers", "Top layers", ""),
    ("bottom_shell_layers", "Bottom layers", ""),
    ("sparse_infill_density", "Infill", ""),
    ("sparse_infill_pattern", "Infill pattern", ""),
    ("seam_position", "Seam", ""),
    ("enable_support", "Supports", _ON_OFF),
    ("support_type", "Support type", ""),
    ("brim_type", "Brim", ""),
    ("ironing_type", "Ironing", ""),
    ("outer_wall_speed", "Outer wall speed", "mm/s"),
    ("inner_wall_speed", "Inner wall speed", "mm/s"),
    ("sparse_infill_speed", "Infill speed", "mm/s"),
    ("outer_wall_acceleration", "Outer wall acceleration", "mm/s²"),
    ("default_acceleration", "Default acceleration", "mm/s²"),
)

_FILAMENT_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("filament_type", "Type", ""),
    ("nozzle_temperature_initial_layer", "Nozzle, first layer", "°C"),
    ("nozzle_temperature", "Nozzle", "°C"),
    ("hot_plate_temp", "Bed (smooth/hot plate)", "°C"),
    ("textured_plate_temp", "Bed (textured plate)", "°C"),
    ("chamber_temperatures", "Chamber", "°C"),
    ("filament_flow_ratio", "Flow ratio", ""),
    ("pressure_advance", "Pressure advance", ""),
    ("filament_max_volumetric_speed", "Max volumetric speed", "mm³/s"),
    ("fan_max_speed", "Part fan, max", "%"),
)


@dataclass(frozen=True, slots=True)
class PresetChanges:
    """What a preset of the user's own changes compared with the preset it is based on."""

    preset: str
    parent: str
    changes: Sequence[tuple[str, Any, Any]] = field(default_factory=tuple)
    """``(setting, value in the parent, value in this preset)`` for each change."""


def write_print_settings(
    directory: Path,
    slicer: str,
    settings_files: Sequence[Path],
    filament_files: Sequence[Path],
    changes: Sequence[PresetChanges] = (),
    *,
    when: datetime,
) -> Path:
    """Write the summary into ``directory`` and return its path.

    ``settings_files`` are the complete printer and process presets written for
    the slicer and ``filament_files`` the filament of each slot, as returned by
    ``PresetLibrary.write_resolved``. Raises ``OSError`` or ``ValueError`` if
    they cannot be read.
    """
    printer, process = _by_type(settings_files)
    filaments = [_read(path) for path in dict.fromkeys(filament_files)]
    text = summary_text(slicer, printer, process, filaments, changes, when=when)
    path = directory / PRINT_SETTINGS
    path.write_text(text, encoding="utf-8")
    return path


def summary_text(
    slicer: str,
    printer: dict[str, Any],
    process: dict[str, Any],
    filaments: Sequence[dict[str, Any]],
    changes: Sequence[PresetChanges] = (),
    *,
    when: datetime,
) -> str:
    """Return the summary for complete printer, process and filament presets."""
    lines = [
        "BatchSlicer print settings",
        "==========================",
        "",
        f"Sliced:   {when:%Y-%m-%d %H:%M} with {slicer}",
        f"Printer:  {_name(printer, 'printer_settings_id')}",
    ]
    for slot, filament in enumerate(filaments, start=1):
        label = "Filament:" if len(filaments) == 1 else f"Filament {slot}:"
        lines.append(f"{label:<10}{_name(filament, 'filament_settings_id')}")
    lines.append(f"Process:  {_name(process, 'print_settings_id')}")

    lines += _section("Printer", printer, _PRINTER_SETTINGS)
    lines += _section("Process preset", process, _PROCESS_SETTINGS)
    for slot, filament in enumerate(filaments, start=1):
        title = "Filament" if len(filaments) == 1 else f"Filament {slot}"
        heading = f"{title}: {_name(filament, 'filament_settings_id')}"
        lines += _section(heading, filament, _FILAMENT_SETTINGS)

    for change in changes:
        if not change.changes:
            continue
        lines += ["", f'Changes in your preset "{change.preset}" (compared with "{change.parent}")']
        for key, before, after in change.changes:
            lines.append(f"  {key}: {_value(before)} -> {_value(after)}")

    lines += [
        "",
        "Every setting is in the presets folder next to this file "
        "(machine.json, process.json, filament.json).",
        "",
    ]
    return "\n".join(lines)


def _section(
    title: str, data: dict[str, Any], settings: Sequence[tuple[str, str, str]]
) -> list[str]:
    """Return a titled list of the settings present in ``data``."""
    rows = [(label, data[key], unit) for key, label, unit in settings if key in data]
    if not rows:
        return []
    width = max(len(label) for label, _, _ in rows)
    lines = ["", title, "-" * len(title)]
    for label, value, unit in rows:
        shown = _value(value)
        if unit == _ON_OFF:
            shown, unit = {"0": "off", "1": "on"}.get(shown, shown), ""
        lines.append(f"  {label:<{width}}  {shown}{' ' + unit if unit and shown else ''}")
    return lines


def _value(value: Any) -> str:
    """Return a preset value as text: lists (one value per extruder or plate) joined."""
    if value is None:
        return "(not set)"
    if isinstance(value, list):
        values = [str(item) for item in value]
        if values and all(item == values[0] for item in values):
            return values[0]
        return ", ".join(values)
    return str(value)


def _name(data: dict[str, Any], id_key: str) -> str:
    """Return a preset's name from its settings id (as the slicer reports it) or its name."""
    value = data.get(id_key) or data.get("name") or "(unknown)"
    return _value(value)


def _by_type(paths: Sequence[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the printer and process presets among ``paths``."""
    found: dict[str, dict[str, Any]] = {}
    for path in paths:
        data = _read(path)
        found[str(data.get("type", ""))] = data
    if "machine" not in found or "process" not in found:
        raise ValueError("The printer or process preset file is missing.")
    return found["machine"], found["process"]


def _read(path: Path) -> dict[str, Any]:
    """Return one preset file's settings."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a preset file.")
    return data
