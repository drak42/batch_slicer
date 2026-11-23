"""Tests for unpacking the models in a zip file."""

import zipfile
from pathlib import Path

import pytest

from batchslicer.services import archives
from batchslicer.services.archives import ArchiveError, extract_models, is_archive, model_names


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_only_models_are_unpacked_and_shared_folders_dropped(tmp_path: Path) -> None:
    """Pictures, text and Mac junk stay behind; kit/files/ is left out of the paths."""
    kit = _zip(tmp_path / "boat-kit.zip", {
        "boat-kit/files/hull.stl": b"solid hull",
        "boat-kit/files/deck/rail.OBJ": b"o rail",
        "boat-kit/images/photo.png": b"PNG",
        "boat-kit/README.txt": b"print me",
        "__MACOSX/boat-kit/files/._hull.stl": b"junk",
        "boat-kit/files/.hidden.stl": b"hidden",
    })

    folder = extract_models(kit, tmp_path / "out")

    assert folder == tmp_path / "out" / "boat-kit"
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
        "deck/rail.OBJ", "hull.stl",
    ]
    assert (folder / "hull.stl").read_bytes() == b"solid hull"
    assert model_names(kit) == ["boat-kit/files/hull.stl", "boat-kit/files/deck/rail.OBJ"]
    assert is_archive(kit) and not is_archive(folder / "hull.stl")


def test_models_at_different_levels_keep_their_folders(tmp_path: Path) -> None:
    """Nothing is left out when the models do not share a folder."""
    kit = _zip(tmp_path / "kit.zip", {"a.stl": b"a", "parts/b.3mf": b"b"})

    folder = extract_models(kit, tmp_path / "out")

    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
        "a.stl", "parts/b.3mf",
    ]


@pytest.mark.parametrize("name", ["../escape.stl", "/etc/escape.stl", "kit/../../escape.stl", "C:/escape.stl"])
def test_paths_outside_the_folder_are_refused(tmp_path: Path, name: str) -> None:
    """An entry that would land outside the target folder stops the unpacking."""
    kit = _zip(tmp_path / "bad.zip", {"ok.stl": b"ok", name: b"evil"})

    with pytest.raises(ArchiveError, match="unsafe file path"):
        extract_models(kit, tmp_path / "out")
    assert not (tmp_path / "escape.stl").exists()
    assert not (tmp_path / "out" / "bad").exists()


def test_archives_without_models_or_unreadable_are_explained(tmp_path: Path) -> None:
    """No models, or not a zip at all, give a clear error and leave nothing behind."""
    pictures = _zip(tmp_path / "pictures.zip", {"photo.png": b"PNG"})
    broken = tmp_path / "broken.zip"
    broken.write_text("not a zip")

    with pytest.raises(ArchiveError, match="holds no model files"):
        extract_models(pictures, tmp_path / "out")
    with pytest.raises(ArchiveError, match="not a readable zip|Could not unpack"):
        extract_models(broken, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_size_limits_stop_huge_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """More than the size limit, or a file that expands suspiciously, is refused and cleaned up."""
    kit = _zip(tmp_path / "big.zip", {"a.stl": b"x" * 4000, "b.stl": b"y" * 4000})
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 5000)
    with pytest.raises(ArchiveError, match="unpacks to more than"):
        extract_models(kit, tmp_path / "out")
    assert not (tmp_path / "out" / "big").exists()

    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr(archives, "_SMALL_FILE", 100)
    bomb = _zip(tmp_path / "bomb.zip", {"zero.stl": b"\0" * 1_000_000})
    with pytest.raises(ArchiveError, match="expands suspiciously"):
        extract_models(bomb, tmp_path / "out")


def test_an_existing_folder_is_never_touched(tmp_path: Path) -> None:
    """If the target folder already exists, unpacking stops and leaves it alone."""
    kit = _zip(tmp_path / "kit.zip", {"a.stl": b"a"})
    existing = tmp_path / "out" / "kit"
    existing.mkdir(parents=True)
    (existing / "mine.txt").write_text("keep me")

    with pytest.raises(ArchiveError, match="already exists"):
        extract_models(kit, tmp_path / "out")
    assert (existing / "mine.txt").read_text() == "keep me"
