"""Tests for putting uploaded models into the watched folder."""

import io
import os
from pathlib import Path, PurePosixPath

import pytest

from batchslicer.services.uploads import (
    STAGING_PREFIX,
    Upload,
    UploadError,
    clean_path,
    describe_size,
    remove_stale_uploads,
)
from batchslicer.services.watching import WatchFolder


@pytest.mark.parametrize(
    ("name", "cleaned"),
    [
        ("cube.stl", "cube.stl"),
        ("kit/parts/a.stl", "kit/parts/a.stl"),
        ("../../etc/cube.stl", "etc/cube.stl"),
        ("/abs/cube.stl", "abs/cube.stl"),
        ("kit\\..\\b.stl", "kit/b.stl"),
        (".hidden/.cube.stl", "hidden/cube.stl"),
        ('we<i>rd:na"me?.stl', "we_i_rd_na_me_.stl"),
        ("CON.stl", "_CON.stl"),
        ("trailing. /x.stl", "trailing/x.stl"),
    ],
)
def test_names_are_made_safe(name: str, cleaned: str) -> None:
    """No .., hidden or absolute paths, or characters Windows refuses."""
    assert clean_path(name) == PurePosixPath(cleaned)


def test_names_with_nothing_left_are_refused() -> None:
    """Only dots, slashes or spaces leave nothing; very deep paths are refused."""
    assert clean_path("../..") is None
    assert clean_path(" / ") is None
    assert clean_path("/".join(["d"] * 30) + "/a.stl") is None
    assert len(str(clean_path("x" * 300 + ".stl"))) == 200


def test_an_upload_arrives_all_at_once(tmp_path: Path) -> None:
    """Files wait in a hidden folder the watcher ignores, then each drop moves in."""
    watched = tmp_path / "in"
    folder = WatchFolder(watched)
    upload = Upload(watched)
    upload.add("cube.stl", io.BytesIO(b"solid"))
    upload.add("kit/a.stl", io.BytesIO(b"solid"))
    upload.add("kit/readme.txt", io.BytesIO(b"text"))
    upload.add("kit.zip", io.BytesIO(b"PK"))
    upload.add("kit/inner.zip", io.BytesIO(b"PK"))  # zip files only work as drops of their own
    upload.add("notes.txt", io.BytesIO(b"text"))
    folder.ready()
    assert folder.ready() == []  # nothing visible to the watcher yet

    result = upload.finish()

    assert result.added == ["cube.stl", "kit", "kit.zip"]
    assert result.skipped == ["kit/readme.txt", "kit/inner.zip", "notes.txt"]
    assert sorted(p.name for p in watched.iterdir()) == ["cube.stl", "kit", "kit.zip"]
    assert [p.name for p in (watched / "kit").iterdir()] == ["a.stl"]


def test_names_already_in_the_folder_get_a_number(tmp_path: Path) -> None:
    """An upload never replaces a waiting drop."""
    (tmp_path / "cube.stl").write_text("old")
    upload = Upload(tmp_path)
    upload.add("cube.stl", io.BytesIO(b"new"))
    assert upload.finish().added == ["cube (2).stl"]
    assert (tmp_path / "cube.stl").read_text() == "old"


def test_limits_refuse_the_whole_upload(tmp_path: Path) -> None:
    """Past the size or file limit, an UploadError is raised; discarding leaves nothing behind."""
    upload = Upload(tmp_path, max_bytes=10)
    with pytest.raises(UploadError, match="Too large"):
        upload.add("big.stl", io.BytesIO(b"x" * 11))
    upload.discard()
    many = Upload(tmp_path, max_files=1)
    many.add("a.stl", io.BytesIO(b"x"))
    with pytest.raises(UploadError, match="Too many files"):
        many.add("b.stl", io.BytesIO(b"x"))
    many.discard()
    assert list(tmp_path.iterdir()) == []


def test_unfinished_uploads_are_removed_after_a_day(tmp_path: Path) -> None:
    """Staging folders a day old go; newer ones and other folders stay."""
    old = tmp_path / f"{STAGING_PREFIX}old"
    new = tmp_path / f"{STAGING_PREFIX}new"
    for folder in (old, new, tmp_path / "kit"):
        folder.mkdir()
    os.utime(old, (1_000, 1_000))
    os.utime(new, (100_000, 100_000))
    remove_stale_uploads(tmp_path, now=lambda: 100_000 + 60)
    assert sorted(p.name for p in tmp_path.iterdir()) == [new.name, "kit"]


def test_limits_are_described_plainly() -> None:
    """Sizes read as people say them."""
    assert describe_size(2 * 1024**3) == "2 GB"
    assert describe_size(500 * 1024**2) == "500 MB"
