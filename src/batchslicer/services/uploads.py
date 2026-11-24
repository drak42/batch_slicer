"""Put uploaded models into the watched folder, safely and all at once.

Files arrive one after another, so they are first written into a hidden
staging folder inside the watched folder (``.batchslicer-upload-*``), which
the watcher ignores. Only when the whole upload has arrived is each of its
top-level entries (a model file, a zip file, or a folder) moved into the
watched folder in one step, so the watcher never sees half an upload.

Names come from a browser, so every part of a path is cleaned: no ``..``, no
hidden or absolute paths, no characters Windows refuses. Only what the
watcher slices is kept: STL, 3MF and OBJ files, and zip files on their own;
anything else is skipped and reported. Sizes are limited. This module only
stores files; it does not slice them or deal with web requests.
"""

import re
import secrets
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from batchslicer.services.watching import MODEL_SUFFIXES, free_name

STAGING_PREFIX = ".batchslicer-upload-"
MAX_UPLOAD_BYTES = 2 * 1024**3
"""The most one upload may hold, all files together."""

MAX_FILES = 1000
"""The most files one upload may hold."""

STALE_SECONDS = 24 * 60 * 60
"""Staging folders older than this were left by an upload that never finished."""

_ARCHIVE_SUFFIX = ".zip"
_CHUNK = 1024 * 1024
_MAX_DEPTH = 20
_MAX_PART = 200
_BAD_CHARACTERS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
)
"""Names Windows keeps for devices, whatever their file type."""


def describe_size(size: int) -> str:
    """Return a size limit as people say it: ``2 GB``, ``500 MB``."""
    if size >= 1024**3:
        return f"{size / 1024**3:g} GB"
    return f"{size / 1024**2:g} MB"


class UploadError(ValueError):
    """Raised when an upload is refused; the message says why."""


@dataclass
class UploadResult:
    """What an upload put into the watched folder, and what it left out."""

    added: list[str] = field(default_factory=list)
    """The drops now in the watched folder, by name."""

    skipped: list[str] = field(default_factory=list)
    """Files left out because the watcher would not slice them, or because of their name."""


def clean_path(name: str) -> PurePosixPath | None:
    """Return an uploaded file's path made safe, or None if nothing usable is left.

    Backslashes count as folder separators; empty parts, ``.`` and ``..`` are
    dropped; leading dots and spaces, and characters Windows refuses, are
    removed or replaced; device names such as ``CON`` get a ``_`` in front.
    """
    parts = []
    for raw in name.replace("\\", "/").split("/"):
        part = _BAD_CHARACTERS.sub("_", raw).strip().lstrip(". ").rstrip(". ")
        if not part:
            continue
        if part.split(".")[0].casefold() in _RESERVED:
            part = f"_{part}"
        if len(part) > _MAX_PART:
            stem, dot, suffix = part.rpartition(".")
            part = (stem[: _MAX_PART - len(suffix) - 1] + dot + suffix) if dot and len(suffix) < 10 else part[:_MAX_PART]
        parts.append(part)
    if not parts or len(parts) > _MAX_DEPTH:
        return None
    return PurePosixPath(*parts)


def wanted(path: PurePosixPath) -> bool:
    """Return whether the watcher slices this uploaded file: models anywhere, zip files only on their own."""
    suffix = path.suffix.casefold()
    return suffix in MODEL_SUFFIXES or (suffix == _ARCHIVE_SUFFIX and len(path.parts) == 1)


class Upload:
    """One upload: files are added to a staging folder, then moved into the watched folder together."""

    def __init__(self, watched: Path, *, max_bytes: int = MAX_UPLOAD_BYTES, max_files: int = MAX_FILES) -> None:
        """Start an upload into ``watched`` (created if missing)."""
        watched.mkdir(parents=True, exist_ok=True)
        self.watched = watched
        self.staging = watched / f"{STAGING_PREFIX}{secrets.token_hex(8)}"
        self.staging.mkdir()
        self.result = UploadResult()
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._bytes = 0
        self._files = 0

    def add(self, name: str, source: BinaryIO) -> None:
        """Copy one uploaded file into the staging folder, or note it as skipped.

        Raises UploadError if the upload grows past its limits.
        """
        path = clean_path(name)
        if path is None or not wanted(path):
            self.result.skipped.append(name)
            return
        self._files += 1
        if self._files > self._max_files:
            raise UploadError(f"Too many files: at most {self._max_files} at a time.")
        target = self.staging.joinpath(*path.parts)
        if target.exists():
            self.result.skipped.append(name)  # the same name twice after cleaning
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            while chunk := source.read(_CHUNK):
                self._bytes += len(chunk)
                if self._bytes > self._max_bytes:
                    raise UploadError(f"Too large: at most {describe_size(self._max_bytes)} at a time.")
                stream.write(chunk)

    def finish(self) -> UploadResult:
        """Move each top-level file and folder into the watched folder, and remove the staging folder.

        A name already in the watched folder gets a number: ``cube (2).stl``.
        """
        try:
            for entry in sorted(self.staging.iterdir(), key=lambda path: path.name.casefold()):
                target = free_name(self.watched / entry.name, keep_suffix=entry.is_file())
                entry.rename(target)
                self.result.added.append(target.name)
        finally:
            self.discard()
        return self.result

    def discard(self) -> None:
        """Remove the staging folder and whatever is left in it."""
        shutil.rmtree(self.staging, ignore_errors=True)


def remove_stale_uploads(watched: Path, *, now: Callable[[], float] = time.time) -> None:
    """Remove staging folders left by uploads that never finished (a day old or more)."""
    try:
        entries = list(watched.glob(f"{STAGING_PREFIX}*"))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and now() - entry.stat().st_mtime >= STALE_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue
