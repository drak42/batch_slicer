"""Find and read the results of earlier runs in the output folder.

Every run writes ``report.json`` into its own folder in the output folder
(``<output>/<run>/``, or ``<output>/<printer>/<run>/`` when one run slices for
several printers). This module finds those folders, newest first, and reads
their reports, for the web page. Paths given to it come from outside (a web
address), so it only ever returns paths inside the output folder. It only
reads; it does not slice, move or delete anything.
"""

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import IO, Any

from batchslicer.services.gcode_stats import format_duration
from batchslicer.services.report import REPORT_CSV, REPORT_JSON

_DEPTHS = ("*/" + REPORT_JSON, "*/*/" + REPORT_JSON)


@dataclass(frozen=True, slots=True)
class ResultRow:
    """One model (or models sliced together on plates) in a run's report."""

    model: str
    success: bool
    gcode: tuple[str, ...]
    """G-code files, relative to the run's folder, with ``/``."""

    model_count: int = 1
    copies: int = 1
    print_time: str = ""
    print_seconds: float | None = None
    filament_g: float | None = None
    filament_g_each: tuple[float, ...] = ()
    """Grams per filament slot, for a multi-colour print."""

    filament_changes: int | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class RunResult:
    """One run's folder in the output folder and its report."""

    name: str
    """The folder relative to the output folder, with ``/``."""

    folder: Path
    finished: datetime
    """When the report was last written."""

    rows: tuple[ResultRow, ...]

    @property
    def succeeded(self) -> int:
        """Return how many model files sliced (models together on plates count each)."""
        return sum(row.model_count for row in self.rows if row.success)

    @property
    def failed(self) -> int:
        """Return how many model files failed."""
        return sum(row.model_count for row in self.rows if not row.success)

    @property
    def print_time(self) -> str:
        """Return the print time of everything that sliced, or an empty string if not known."""
        seconds = [row.print_seconds for row in self.rows if row.success and row.print_seconds]
        return format_duration(sum(seconds)) if seconds else ""

    @property
    def filament_g(self) -> float | None:
        """Return the grams of filament of everything that sliced, if known."""
        grams = [row.filament_g for row in self.rows if row.success and row.filament_g is not None]
        return round(sum(grams), 1) if grams else None

    @property
    def gcode(self) -> tuple[str, ...]:
        """Return every G-code file of the run, relative to its folder."""
        return tuple(path for row in self.rows for path in row.gcode)


def find_results(output: Path, limit: int = 30) -> list[RunResult]:
    """Return up to ``limit`` runs in ``output``, the most recently finished first.

    Folders whose report cannot be read are left out.
    """
    try:
        reports = [
            path
            for pattern in _DEPTHS
            for path in output.glob(pattern)
            if not any(part.startswith(".") for part in path.relative_to(output).parts)
        ]
    except OSError:
        return []
    dated = []
    for path in reports:
        try:
            dated.append((path.stat().st_mtime, path))
        except OSError:
            continue
    dated.sort(reverse=True)
    results = []
    for _, path in dated:
        result = _read(output, path.parent)
        if result is not None:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def get_result(output: Path, name: str) -> RunResult | None:
    """Return the run in the folder ``name`` (relative to ``output``), or None if there is none."""
    folder = inside(output, name)
    if folder is None or not (folder / REPORT_JSON).is_file():
        return None
    return _read(output, folder)


def inside(base: Path, relative: str) -> Path | None:
    """Return ``base / relative`` if it stays inside ``base``, else None.

    Absolute paths, ``..`` and links that lead out of ``base`` are refused.
    """
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or ".." in parts or "\\" in relative:
        return None
    try:
        root = base.resolve()
        path = (root / Path(*parts)).resolve()
    except (OSError, ValueError):
        return None
    return path if path.is_relative_to(root) and path != root else None


def downloadable(path: Path) -> bool:
    """Return whether a file of a run may be downloaded: its G-code and its reports."""
    return path.suffix.casefold() == ".gcode" or path.name in (REPORT_CSV, REPORT_JSON)


def write_zip(result: RunResult, target: IO[bytes]) -> int:
    """Write a run's G-code files and reports into a ZIP file, keeping their folders.

    Everything sits in a folder named after the run. Returns how many files were written.
    """
    names = [*result.gcode, REPORT_CSV, REPORT_JSON]
    top = PurePosixPath(result.name).name
    written = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in dict.fromkeys(names):
            path = inside(result.folder, name)
            if path is None or not path.is_file():
                continue
            archive.write(path, f"{top}/{name}")
            written += 1
    return written


def _read(output: Path, folder: Path) -> RunResult | None:
    """Read one run's report, or return None if it cannot be read."""
    path = folder / REPORT_JSON
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        finished = datetime.fromtimestamp(path.stat().st_mtime)
        rows = tuple(_row(item) for item in data["models"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return RunResult(
        name=folder.relative_to(output).as_posix(),
        folder=folder,
        finished=finished,
        rows=rows,
    )


def _row(item: dict[str, Any]) -> ResultRow:
    """Return one report row."""
    return ResultRow(
        model=str(item["model"]),
        success=item.get("status") == "ok",
        gcode=tuple(str(path) for path in item.get("gcode") or ()),
        model_count=len(item.get("models") or ()) or 1,
        copies=int(item.get("copies") or 1),
        print_time=str(item.get("print_time") or ""),
        print_seconds=item.get("print_seconds"),
        filament_g=item.get("filament_g"),
        filament_g_each=tuple(float(grams) for grams in item.get("filament_g_each") or ()),
        filament_changes=item.get("filament_changes"),
        message=str(item.get("message") or ""),
    )
