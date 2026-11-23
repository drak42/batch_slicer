"""Write a report of a slicing run: one row per model (or plate group), as CSV and JSON.

``report.csv`` opens in any spreadsheet for costing and planning;
``report.json`` holds the same rows for scripts. Both are written into the
run's output folder, and rewritten as the run goes so an interrupted run still
has a report of what was finished. Print time and filament come from the
G-code statistics read when each model was sliced. This module only writes
files; it does not slice.
"""

import csv
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from batchslicer.services.gcode_stats import format_duration
from batchslicer.services.slicing import SliceOutcome

REPORT_CSV = "report.csv"
REPORT_JSON = "report.json"

COLUMNS = (
    "model",
    "models",
    "copies",
    "status",
    "auto_oriented",
    "gcode",
    "print_time",
    "print_seconds",
    "filament_g",
    "filament_m",
    "filament_cost",
    "filament_g_each",
    "filament_changes",
    "slice_seconds",
    "message",
)
"""The report's columns, in order."""


def report_rows(outcomes: Sequence[SliceOutcome], directory: Path, root: Path) -> list[dict[str, Any]]:
    """Return one row per outcome; paths are relative to ``root`` (models) and ``directory`` (G-code)."""
    rows = []
    for outcome in outcomes:
        stats = outcome.stats
        rows.append(
            {
                "model": _relative(outcome.model, root),
                "models": [_relative(path, root) for path in outcome.models],
                "copies": outcome.copies,
                "status": "ok" if outcome.success else "failed",
                "auto_oriented": outcome.auto_oriented,
                "gcode": [_relative(path, directory) for path in outcome.gcode_files],
                "print_time": (
                    format_duration(stats.print_seconds) if stats.print_seconds is not None else None
                ),
                "print_seconds": _rounded(stats.print_seconds, 0),
                "filament_g": _rounded(stats.filament_grams, 2),
                "filament_m": _rounded(
                    stats.filament_millimetres / 1000 if stats.filament_millimetres is not None else None,
                    3,
                ),
                "filament_cost": _rounded(stats.filament_cost, 2),
                "filament_g_each": [round(grams, 2) for grams in stats.grams_per_filament]
                if len(stats.used_filaments()) > 1
                else [],
                "filament_changes": stats.filament_changes if len(stats.used_filaments()) > 1 else None,
                "slice_seconds": round(outcome.elapsed, 1),
                "message": "" if outcome.success else outcome.message,
            }
        )
    return rows


def write_report(
    outcomes: Sequence[SliceOutcome],
    directory: Path,
    root: Path,
) -> tuple[Path, Path]:
    """Write ``report.csv`` and ``report.json`` into ``directory`` and return their paths.

    Each file is replaced atomically, so a reader never sees half a report.
    """
    rows = report_rows(outcomes, directory, root)
    csv_path = directory / REPORT_CSV
    json_path = directory / REPORT_JSON

    def write_csv(file: Any) -> None:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "auto_oriented": "yes" if row["auto_oriented"] else "",
                    "gcode": "; ".join(row["gcode"]),
                    "models": "; ".join(row["models"]),
                    "filament_g_each": "; ".join(str(grams) for grams in row["filament_g_each"]),
                }
            )

    def write_json(file: Any) -> None:
        json.dump({"models": rows}, file, indent=2, ensure_ascii=False)
        file.write("\n")

    _replace(csv_path, write_csv, newline="")
    _replace(json_path, write_json)
    return csv_path, json_path


def _replace(path: Path, write: Any, *, newline: str | None = None) -> None:
    """Write a file through a temporary file in the same folder, then swap it in."""
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline=newline,
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        write(temporary)
    Path(temporary.name).replace(path)


def _relative(path: Path, base: Path) -> str:
    """Return ``path`` relative to ``base`` when it is inside it (with ``/`` on every system), else as given."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _rounded(value: float | None, digits: int) -> float | None:
    """Round an optional value."""
    if value is None:
        return None
    return round(value, digits) if digits else float(round(value))
