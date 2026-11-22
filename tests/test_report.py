"""Tests for the batch report."""

import csv
import json
from pathlib import Path

from batchslicer.services.gcode_stats import GcodeStats
from batchslicer.services.report import COLUMNS, write_report
from batchslicer.services.slicing import SliceOutcome


def _outcomes(batch: Path, root: Path) -> list[SliceOutcome]:
    """Return one successful (auto-oriented) and one failed outcome."""
    return [
        SliceOutcome(
            success=True,
            model=root / "sub" / "part.stl",
            job_directory=batch / "sub" / "part",
            gcode_files=(batch / "sub" / "part" / "part.gcode",),
            message="Success.",
            elapsed=2.94,
            auto_oriented=True,
            stats=GcodeStats(3730.0, 7.414, 2485.84, 0.15),
        ),
        SliceOutcome(
            success=False,
            model=root / "bad.3mf",
            job_directory=batch / "bad",
            gcode_files=(),
            message="Unsupported 3MF version.",
            elapsed=0.5,
        ),
    ]


def test_report_is_written_as_csv_and_json(tmp_path: Path) -> None:
    """Every model gets a row with status, G-code, print time, filament and reason."""
    root = tmp_path / "models"
    batch = tmp_path / "out" / "models-1"
    batch.mkdir(parents=True)

    csv_path, json_path = write_report(_outcomes(batch, root), batch, root)

    with csv_path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert tuple(rows[0]) == COLUMNS
    assert rows[0] == {
        "model": "sub/part.stl",
        "status": "ok",
        "auto_oriented": "yes",
        "gcode": "sub/part/part.gcode",
        "models": "",
        "copies": "1",
        "print_time": "1h 2m",
        "print_seconds": "3730.0",
        "filament_g": "7.41",
        "filament_m": "2.486",
        "filament_cost": "0.15",
        "slice_seconds": "2.9",
        "message": "",
    }
    assert rows[1]["status"] == "failed"
    assert rows[1]["message"] == "Unsupported 3MF version."
    assert rows[1]["print_time"] == ""

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["models"][0]["gcode"] == ["sub/part/part.gcode"]
    assert data["models"][1]["filament_g"] is None
    assert sorted(path.name for path in batch.iterdir()) == ["report.csv", "report.json"]
