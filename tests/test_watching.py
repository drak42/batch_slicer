"""Tests for watching a folder for models to slice."""

import os
from pathlib import Path

import pytest

from batchslicer.services.watching import WatchFolder, WatchSummary, watch


def _write(path: Path, text: str = "solid cube\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_drop_is_ready_once_it_stops_changing(tmp_path: Path) -> None:
    """The first look only notes a drop; it is ready when the next look finds it unchanged."""
    folder = WatchFolder(tmp_path)
    cube = _write(tmp_path / "cube.stl")

    assert folder.ready() == []
    assert folder.ready() == [cube]


def test_a_growing_file_waits(tmp_path: Path) -> None:
    """A file still being written is not ready until two looks agree."""
    folder = WatchFolder(tmp_path)
    cube = _write(tmp_path / "cube.stl", "solid")
    folder.ready()
    cube.write_text("solid cube, more of it")

    assert folder.ready() == []
    assert folder.ready() == [cube]


def test_a_folder_is_ready_when_nothing_in_it_changes(tmp_path: Path) -> None:
    """Adding a file to a folder drop makes it wait another look."""
    folder = WatchFolder(tmp_path)
    kit = tmp_path / "kit"
    _write(kit / "left.stl")
    folder.ready()
    _write(kit / "parts" / "right.stl")

    assert folder.ready() == []
    assert folder.ready() == [kit]


def test_unfinished_downloads_hold_a_folder_back(tmp_path: Path) -> None:
    """A folder with a .part or .crdownload file inside is never ready."""
    folder = WatchFolder(tmp_path)
    _write(tmp_path / "kit" / "left.stl")
    _write(tmp_path / "kit" / "right.stl.crdownload")
    _write(tmp_path / "loose.stl.part")

    folder.ready()
    assert folder.ready() == []


def test_things_that_are_not_drops_are_ignored(tmp_path: Path) -> None:
    """Hidden entries, other file types, folders without models and the result folders are left alone."""
    folder = WatchFolder(tmp_path)
    _write(tmp_path / ".hidden.stl")
    _write(tmp_path / "notes.txt")
    _write(tmp_path / "pictures" / "photo.jpg")
    _write(tmp_path / "sliced" / "old.stl")
    _write(tmp_path / "failed" / "broken.stl")
    model = _write(tmp_path / "Bracket.3MF")

    folder.ready()
    assert folder.ready() == [model]


def test_drops_are_handled_in_name_order(tmp_path: Path) -> None:
    """Several ready drops come back sorted by name, ignoring case."""
    folder = WatchFolder(tmp_path)
    names = ["b.stl", "A.obj", "c"]
    for name in names:
        _write(tmp_path / name / "m.stl" if name == "c" else tmp_path / name)
    folder.ready()

    assert [path.name for path in folder.ready()] == ["A.obj", "b.stl", "c"]


def test_finished_drops_move_and_are_not_returned_again(tmp_path: Path) -> None:
    """Successful drops go to sliced/, failed ones to failed/, with free names."""
    folder = WatchFolder(tmp_path)
    _write(tmp_path / "sliced" / "cube.stl", "an earlier cube")
    _write(tmp_path / "sliced" / "kit" / "a.stl")
    cube = _write(tmp_path / "cube.stl")
    kit = _write(tmp_path / "kit" / "a.stl").parent
    broken = _write(tmp_path / "broken.stl")

    assert folder.finish(cube, success=True) == tmp_path / "sliced" / "cube (2).stl"
    assert folder.finish(kit, success=True) == tmp_path / "sliced" / "kit (2)"
    assert folder.finish(broken, success=False) == tmp_path / "failed" / "broken.stl"
    assert (tmp_path / "sliced" / "kit (2)" / "a.stl").is_file()
    folder.ready()
    assert folder.ready() == []


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs Unix permissions as a normal user")
def test_a_drop_that_cannot_be_moved_is_not_sliced_again(tmp_path: Path) -> None:
    """If moving fails, the drop is remembered as handled until it changes."""
    folder = WatchFolder(tmp_path)
    cube = _write(tmp_path / "cube.stl")
    folder.ready()
    assert folder.ready() == [cube]
    tmp_path.chmod(0o555)
    try:
        assert folder.finish(cube, success=True) is None
    finally:
        tmp_path.chmod(0o755)

    assert folder.ready() == []
    cube.write_text("solid changed cube")
    folder.ready()
    assert folder.ready() == [cube]


def test_the_watched_folder_is_created(tmp_path: Path) -> None:
    """A missing watched folder is made, so it can be dropped into."""
    WatchFolder(tmp_path / "incoming")
    assert (tmp_path / "incoming").is_dir()


def test_watch_slices_each_drop_until_interrupted(tmp_path: Path) -> None:
    """watch() hands each ready drop over, moves it, and stops cleanly on Ctrl+C."""
    _write(tmp_path / "good.stl")
    _write(tmp_path / "bad.stl")
    handled: list[str] = []
    moved: list[tuple[str, str | None, bool]] = []
    looks = 0

    def sleep(seconds: float) -> None:
        nonlocal looks
        looks += 1
        if looks == 3:
            raise KeyboardInterrupt

    def handle(drop: Path) -> bool:
        handled.append(drop.name)
        return drop.name == "good.stl"

    summary = watch(
        WatchFolder(tmp_path),
        handle,
        interval=0,
        sleep=sleep,
        on_moved=lambda drop, to, ok: moved.append((drop.name, to.parent.name if to else None, ok)),
    )

    assert summary == WatchSummary(sliced=1, failed=1)
    assert handled == ["bad.stl", "good.stl"]
    assert moved == [("bad.stl", "failed", False), ("good.stl", "sliced", True)]


def test_a_drop_interrupted_while_slicing_stays_put(tmp_path: Path) -> None:
    """Ctrl+C during slicing stops watching without moving the drop."""
    cube = _write(tmp_path / "cube.stl")

    def handle(drop: Path) -> bool:
        raise KeyboardInterrupt

    summary = watch(WatchFolder(tmp_path), handle, interval=0, sleep=lambda _: None)

    assert summary == WatchSummary()
    assert cube.is_file()


def test_zip_files_are_drops(tmp_path: Path) -> None:
    """A downloaded kit dropped as a zip file is a drop; other files are not."""
    import zipfile

    folder = WatchFolder(tmp_path)
    with zipfile.ZipFile(tmp_path / "kit.zip", "w") as archive:
        archive.writestr("kit/a.stl", "solid")
    _write(tmp_path / "notes.txt")

    folder.ready()
    assert folder.ready() == [tmp_path / "kit.zip"]
