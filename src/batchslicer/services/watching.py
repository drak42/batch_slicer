"""Watch a folder for models to slice.

Each model file, zip file or folder put directly in the watched folder is one drop. A
drop is ready once it has stopped changing between two looks, so a file still
being copied or downloaded is left alone until it is complete. After slicing,
the drop is moved into the watched folder's ``sliced`` or ``failed``
subfolder, so it is not sliced again and the folder shows what is left to do.
The folder is looked at every few seconds rather than through system
notifications, which works the same on every system and on network folders.
This module finds and moves drops; it does not slice them.
"""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

SLICED_FOLDER = "sliced"
FAILED_FOLDER = "failed"
DEFAULT_INTERVAL_SECONDS = 5.0

MODEL_SUFFIXES = frozenset({".stl", ".3mf", ".obj"})
"""File types that make a drop worth slicing; the same as ``cli.file_prompt.MODEL_SUFFIXES``."""

_ARCHIVE_SUFFIXES = frozenset({".zip"})
"""Archives (a downloaded kit) are drops too; whoever slices them unpacks them."""

_PARTIAL_SUFFIXES = frozenset({".part", ".partial", ".crdownload", ".download", ".tmp", ".filepart"})
"""Files browsers and copy tools write while a download or copy is unfinished."""

_Signature = tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class WatchSummary:
    """How many drops a watch handled before it stopped."""

    sliced: int = 0
    failed: int = 0


class WatchFolder:
    """Find finished drops in one folder and move them once handled."""

    def __init__(self, root: Path, *, logger: logging.Logger | None = None) -> None:
        """Watch ``root``; it is created if missing."""
        self.root = root
        self.sliced = root / SLICED_FOLDER
        self.failed = root / FAILED_FOLDER
        self._logger = logger or logging.getLogger("batchslicer")
        self._seen: dict[Path, _Signature] = {}
        self._handled: dict[Path, _Signature] = {}
        root.mkdir(parents=True, exist_ok=True)

    def ready(self) -> list[Path]:
        """Return the drops that have not changed since the last look, by name.

        The first look only notes what is there; a drop is returned from the
        second look on. Drops without any model file are never returned.
        """
        current: dict[Path, _Signature] = {}
        for entry in self._entries():
            signature = _signature(entry)
            if signature is not None:
                current[entry] = signature
        ready = [
            entry
            for entry, signature in current.items()
            if self._seen.get(entry) == signature
            and self._handled.get(entry) != signature
            and _has_models(entry, signature)
        ]
        self._seen = current
        return sorted(ready, key=lambda path: path.name.casefold())

    def finish(self, drop: Path, *, success: bool) -> Path | None:
        """Move a handled drop into ``sliced`` or ``failed``; return where it went.

        If it cannot be moved, it is remembered as handled (until it changes)
        so it is not sliced again, and None is returned.
        """
        target_folder = self.sliced if success else self.failed
        try:
            target_folder.mkdir(exist_ok=True)
            target = free_name(target_folder / drop.name, keep_suffix=drop.is_file())
            drop.rename(target)
        except OSError as error:
            self._logger.warning("Could not move %s to %s: %s", drop, target_folder, error)
            signature = _signature(drop)
            if signature is not None:
                self._handled[drop] = signature
            return None
        self._seen.pop(drop, None)
        self._handled.pop(drop, None)
        return target

    def _entries(self) -> Iterable[Path]:
        """Yield the files and folders directly in the watched folder that could be drops."""
        try:
            yield from candidates(self.root)
        except OSError as error:
            self._logger.warning("Cannot read %s: %s", self.root, error)


def candidates(root: Path) -> list[Path]:
    """Return the files and folders directly in ``root`` that could be drops, by name.

    Hidden entries and the ``sliced`` and ``failed`` subfolders are left out;
    whether a drop has finished copying is not checked. Raises OSError if
    ``root`` cannot be read.
    """
    found = []
    for entry in root.iterdir():
        if entry.name.startswith(".") or entry.name in (SLICED_FOLDER, FAILED_FOLDER):
            continue
        suffix = entry.suffix.casefold()
        if entry.is_dir() or (entry.is_file() and suffix in MODEL_SUFFIXES | _ARCHIVE_SUFFIXES):
            found.append(entry)
    return sorted(found, key=lambda path: path.name.casefold())


def watch(
    folder: WatchFolder,
    handle: Callable[[Path], bool],
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    on_moved: Callable[[Path, Path | None, bool], None] | None = None,
) -> WatchSummary:
    """Look at ``folder`` every ``interval`` seconds and ``handle`` each ready drop.

    ``handle`` slices a drop and returns whether everything in it succeeded;
    the drop is then moved and ``on_moved(drop, new place or None, success)``
    is called. Runs until interrupted (Ctrl+C); a drop being sliced when that
    happens stays where it is. Returns how many drops were handled.
    """
    sliced = failed = 0
    try:
        while True:
            for drop in folder.ready():
                success = handle(drop)
                moved = folder.finish(drop, success=success)
                if success:
                    sliced += 1
                else:
                    failed += 1
                if on_moved is not None:
                    on_moved(drop, moved, success)
            sleep(interval)
    except KeyboardInterrupt:
        return WatchSummary(sliced=sliced, failed=failed)


def _signature(entry: Path) -> _Signature | None:
    """Return the names, sizes and change times of a drop's files, or None if it is gone.

    A folder still holding a partly downloaded or copied file gets a
    signature that never repeats, so it is not ready yet.
    """
    try:
        if entry.is_file():
            info = entry.stat()
            return (("", info.st_size, info.st_mtime_ns),)
        files: list[tuple[str, int, int]] = []
        for path in entry.rglob("*"):
            if path.is_file():
                if path.suffix.casefold() in _PARTIAL_SUFFIXES:
                    return (("", -1, time.monotonic_ns()),)
                info = path.stat()
                files.append((path.relative_to(entry).as_posix(), info.st_size, info.st_mtime_ns))
        return tuple(sorted(files))
    except OSError:
        return None


def _has_models(entry: Path, signature: _Signature) -> bool:
    """Return whether a drop holds at least one model file."""
    if entry.is_file():
        return True
    return any(Path(name).suffix.casefold() in MODEL_SUFFIXES for name, _, _ in signature)


def free_name(target: Path, *, keep_suffix: bool) -> Path:
    """Return ``target``, or ``name (2)``, ``name (3)``... if it already exists.

    With ``keep_suffix`` (a file) the number goes before the file type:
    ``cube (2).stl``.
    """
    if not target.exists():
        return target
    stem, suffix = (target.stem, target.suffix) if keep_suffix else (target.name, "")
    number = 2
    while True:
        candidate = target.with_name(f"{stem} ({number}){suffix}")
        if not candidate.exists():
            return candidate
        number += 1
