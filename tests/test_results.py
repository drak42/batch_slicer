"""Tests for finding and reading results in the output folder."""

import json
import os
import sys
from pathlib import Path

import pytest

from batchslicer.services.results import find_results, get_result, inside


def _run(output: Path, name: str, rows: list[dict[str, object]], *, age: int = 0) -> Path:
    folder = output / name
    folder.mkdir(parents=True)
    report = folder / "report.json"
    report.write_text(json.dumps({"models": rows}), encoding="utf-8")
    stamp = 1_800_000_000 - age
    os.utime(report, (stamp, stamp))
    return folder


_OK = {"model": "cube.stl", "status": "ok", "gcode": ["cube/cube.gcode"], "print_time": "1h 4m",
       "print_seconds": 3840.0, "filament_g": 40.78, "filament_g_each": [], "models": [], "copies": 1}
_FAILED = {"model": "broken.stl", "status": "failed", "gcode": [], "message": "Nothing to be sliced"}


def test_results_are_found_newest_first(tmp_path: Path) -> None:
    """Runs one or two folders deep are found, newest first; hidden and unreadable ones are not."""
    _run(tmp_path, "old-20261120-100000", [_OK], age=100)
    _run(tmp_path, "k2/new-20261124-100000", [_OK, _FAILED], age=1)
    _run(tmp_path, ".hidden", [_OK])
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "report.json").write_text("{")

    results = find_results(tmp_path)

    assert [result.name for result in results] == ["k2/new-20261124-100000", "old-20261120-100000"]
    newest = results[0]
    assert (newest.succeeded, newest.failed) == (1, 1)
    assert newest.print_time == "1h 4m"
    assert newest.filament_g == 40.8
    assert newest.gcode == ("cube/cube.gcode",)
    assert newest.rows[1].message == "Nothing to be sliced"
    plates = _run(tmp_path, "plates", [{**_OK, "models": ["a.stl", "b.stl"]}], age=200)
    assert find_results(tmp_path)[-1].folder == plates and find_results(tmp_path)[-1].succeeded == 2
    assert find_results(tmp_path, limit=1) == results[:1]
    assert find_results(tmp_path / "missing") == []


def test_a_result_is_read_by_its_name(tmp_path: Path) -> None:
    """get_result reads one run; names outside the output folder are refused."""
    _run(tmp_path / "out", "cube-20261124-100000", [_OK])
    _run(tmp_path, "secret", [_OK])

    found = get_result(tmp_path / "out", "cube-20261124-100000")
    assert found is not None and found.rows[0].print_seconds == 3840.0
    assert get_result(tmp_path / "out", "../secret") is None
    assert get_result(tmp_path / "out", "missing") is None


@pytest.mark.parametrize("name", ["../x", "/etc/passwd", "a/../../x", "", ".", "a\\..\\..\\x"])
def test_paths_cannot_leave_the_folder(tmp_path: Path, name: str) -> None:
    """Absolute paths, .. and backslashes are refused."""
    assert inside(tmp_path, name) is None


@pytest.mark.skipif(sys.platform == "win32", reason="links need extra rights on Windows")
def test_links_cannot_leave_the_folder(tmp_path: Path) -> None:
    """A link inside the folder that leads out of it is refused."""
    (tmp_path / "out").mkdir()
    (tmp_path / "elsewhere.gcode").write_text("G1")
    (tmp_path / "out" / "link.gcode").symlink_to(tmp_path / "elsewhere.gcode")
    assert inside(tmp_path / "out", "link.gcode") is None
    (tmp_path / "out" / "real.gcode").write_text("G1")
    assert inside(tmp_path / "out", "real.gcode") == (tmp_path / "out" / "real.gcode").resolve()
