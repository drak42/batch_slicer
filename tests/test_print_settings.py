"""Tests for the plain-text summary of the presets a run was sliced with."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from batchslicer.services.print_settings import (
    PRINT_SETTINGS,
    PresetChanges,
    summary_text,
    write_print_settings,
)

WHEN = datetime(2026, 11, 28, 10, 15)
PRINTER = {"type": "machine", "name": "K2 Plus", "printer_settings_id": "Creality K2 Plus 0.4 nozzle",
           "nozzle_diameter": ["0.4"]}
PROCESS = {"type": "process", "name": "x", "print_settings_id": "0.12mm Quality",
           "layer_height": "0.12", "wall_loops": "3", "sparse_infill_density": "15%",
           "outer_wall_speed": "60", "enable_support": "1", "unlisted_setting": "7"}
PLA = {"type": "filament", "filament_settings_id": ["My PLA"], "filament_type": ["PLA"],
       "nozzle_temperature": ["220", "220"], "hot_plate_temp": ["55"]}


def test_summary_names_the_printer_filament_and_process_and_their_settings() -> None:
    """The summary names every preset and lists the main settings with units."""
    text = summary_text("Creality Print", PRINTER, PROCESS, [PLA], when=WHEN)

    assert "Sliced:   2026-11-28 10:15 with Creality Print" in text
    assert "Printer:  Creality K2 Plus 0.4 nozzle" in text
    assert "Filament: My PLA" in text
    assert "Process:  0.12mm Quality" in text
    assert "Layer height      0.12 mm" in text
    assert "Walls             3" in text
    assert "Infill            15%" in text
    assert "Outer wall speed  60 mm/s" in text
    assert re.search(r"\n  Nozzle +220 °C\n", text)  # one value for every extruder, shown once
    assert "Nozzle diameter  0.4 mm" in text
    assert re.search(r"\n  Supports +on\n", text)
    assert "unlisted_setting" not in text
    assert "presets folder" in text


def test_each_filament_slot_is_listed() -> None:
    """A multi-material run lists the filament of every slot."""
    petg = {"type": "filament", "filament_settings_id": ["PETG Black"], "filament_type": ["PETG"]}

    text = summary_text("OrcaSlicer", PRINTER, PROCESS, [PLA, petg], when=WHEN)

    assert "Filament 1: My PLA" in text
    assert "Filament 2: PETG Black" in text


def test_a_users_changes_are_listed_against_the_base_preset() -> None:
    """What the user's own preset changes is listed, old value then new value."""
    changes = [PresetChanges("0.12mm Quality", "0.20mm Standard", (("layer_height", "0.2", "0.12"),
                                                                   ("brim_type", None, "no_brim")))]

    text = summary_text("Creality Print", PRINTER, PROCESS, [PLA], changes, when=WHEN)

    assert 'Changes in your preset "0.12mm Quality" (compared with "0.20mm Standard")' in text
    assert "  layer_height: 0.2 -> 0.12" in text
    assert "  brim_type: (not set) -> no_brim" in text


def test_the_summary_is_written_from_the_preset_files(tmp_path: Path) -> None:
    """The file is written into the result folder from the complete preset files."""
    presets = tmp_path / "presets"
    presets.mkdir()
    files = {}
    for name, data in (("machine", PRINTER), ("process", PROCESS), ("filament", PLA)):
        files[name] = presets / f"{name}.json"
        files[name].write_text(json.dumps(data), encoding="utf-8")

    path = write_print_settings(
        tmp_path, "Creality Print", [files["machine"], files["process"]], [files["filament"]], when=WHEN
    )

    assert path == tmp_path / PRINT_SETTINGS
    assert "Process:  0.12mm Quality" in path.read_text(encoding="utf-8")


def test_missing_preset_files_raise(tmp_path: Path) -> None:
    """Without the printer and process files there is nothing to summarise."""
    with pytest.raises(OSError):
        write_print_settings(tmp_path, "OrcaSlicer", [tmp_path / "machine.json"], [], when=WHEN)
