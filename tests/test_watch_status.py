"""Tests for the watch folder's status file."""

from datetime import datetime
from pathlib import Path

from batchslicer.services import watch_status
from batchslicer.services.watch_status import STATUS_FILE, StatusWriter, read_status
from batchslicer.services.watching import WatchFolder


def _writer(tmp_path: Path, **kwargs: object) -> StatusWriter:
    return StatusWriter(tmp_path, tmp_path / "out", clock=lambda: datetime(2026, 11, 24, 9, 30), **kwargs)  # type: ignore[arg-type]


def test_the_status_follows_the_watcher(tmp_path: Path) -> None:
    """Watching, slicing with progress, a finished drop, and stopped, as a reader sees them."""
    writer = _writer(tmp_path)
    writer.watching()
    assert read_status(tmp_path).state == "watching"  # type: ignore[union-attr]

    writer.slicing("kit")
    writer.progress(2, 5, "parts/b.stl")
    status = read_status(tmp_path)
    assert status is not None
    assert (status.state, status.drop, status.number, status.count, status.model) == ("slicing", "kit", 2, 5, "parts/b.stl")
    assert status.output == str(tmp_path / "out")
    assert status.updated == "2026-11-24T09:30:00"

    writer.finished("kit", success=True, moved_to="sliced/kit")
    writer.stopped()
    status = read_status(tmp_path)
    assert status is not None and status.state == "stopped" and status.drop == ""
    assert [(drop.name, drop.success, drop.moved_to) for drop in status.recent] == [("kit", True, "sliced/kit")]


def test_only_the_latest_drops_are_remembered(tmp_path: Path) -> None:
    """The newest drops come first, up to RECENT_DROPS."""
    writer = _writer(tmp_path)
    for number in range(watch_status.RECENT_DROPS + 5):
        writer.finished(f"drop{number}", success=True)
    recent = read_status(tmp_path).recent  # type: ignore[union-attr]
    assert len(recent) == watch_status.RECENT_DROPS
    assert recent[0].name == f"drop{watch_status.RECENT_DROPS + 4}"


def test_the_status_file_is_never_a_drop(tmp_path: Path) -> None:
    """It is hidden, so the watcher leaves it alone."""
    _writer(tmp_path).watching()
    folder = WatchFolder(tmp_path)
    folder.ready()
    assert folder.ready() == []
    assert (tmp_path / STATUS_FILE).is_file()


def test_a_missing_or_damaged_status_file_reads_as_none(tmp_path: Path) -> None:
    """No file, or one that is not a status, gives None."""
    assert read_status(tmp_path) is None
    (tmp_path / STATUS_FILE).write_text('{"state": "watching"}')
    assert read_status(tmp_path) is None
    (tmp_path / STATUS_FILE).write_text("not json")
    assert read_status(tmp_path) is None


def test_a_status_that_cannot_be_written_does_not_stop_the_watcher(tmp_path: Path) -> None:
    """Errors go to on_error; nothing is raised."""
    errors: list[OSError] = []
    writer = StatusWriter(tmp_path / "missing", tmp_path, on_error=errors.append)
    writer.slicing("cube.stl")
    assert len(errors) == 1
    assert writer.status.state == "slicing"
