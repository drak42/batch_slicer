"""Unpack the models in a zip file, such as a kit downloaded from a model site.

Only model files (STL, 3MF, OBJ) are taken out; pictures, instructions and
the rest stay in the archive. Unpacking is careful with files from the
internet: an entry whose path would land outside the target folder (``../``
or an absolute path) is refused, and the number of files, their total size
and how much they expand are limited, so a small archive cannot fill the disk.
Mac junk (``__MACOSX/``, ``._`` files) and hidden files are skipped. Folders that
every model sits in are left out, so ``kit.zip`` with ``kit/files/part.stl``
unpacks to ``kit/part.stl``, not ``kit/kit/files/part.stl``. This module does not slice anything.
"""

import shutil
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_SUFFIXES = frozenset({".zip"})
MODEL_SUFFIXES = frozenset({".stl", ".3mf", ".obj"})
"""Files taken out of an archive; the same as ``cli.file_prompt.MODEL_SUFFIXES``."""

MAX_FILES = 5000
MAX_TOTAL_BYTES = 4 * 1024**3
"""The most an archive's models may unpack to (4 GB)."""

MAX_RATIO = 200
"""The most a file may expand compared with its compressed size, beyond a small allowance."""

_SMALL_FILE = 10 * 1024 * 1024
_CHUNK = 1024 * 1024


class ArchiveError(ValueError):
    """Raised when an archive cannot be unpacked safely, or holds no models."""


def is_archive(path: Path) -> bool:
    """Return whether ``path`` is an existing zip file."""
    return path.suffix.casefold() in ARCHIVE_SUFFIXES and path.is_file()


def model_names(path: Path) -> list[str]:
    """Return the model files listed in an archive (paths inside it), without unpacking."""
    try:
        with zipfile.ZipFile(path) as archive:
            return [info.filename for info in archive.infolist() if _is_model(info)]
    except (OSError, zipfile.BadZipFile) as error:
        raise ArchiveError(f"{path.name} is not a readable zip file: {error}") from error


def extract_models(path: Path, destination: Path) -> Path:
    """Unpack the models of the archive at ``path`` into ``destination/<archive name>``.

    Returns that folder. Raises :class:`ArchiveError` if the archive cannot be
    read, holds no models, or breaks a safety limit; nothing is left behind
    then.
    """
    target = destination / path.stem
    created = False
    try:
        with zipfile.ZipFile(path) as archive:
            entries = [info for info in archive.infolist() if _is_model(info)]
            if not entries:
                raise ArchiveError(
                    f"{path.name} holds no model files (STL, 3MF, OBJ) to slice."
                )
            if len(entries) > MAX_FILES:
                raise ArchiveError(f"{path.name} holds more than {MAX_FILES} model files.")
            names = [_safe_name(info.filename, path) for info in entries]
            prefix = _shared_top_folder(names)
            if target.exists():
                raise ArchiveError(f"{target} already exists; not unpacking over it.")
            target.mkdir(parents=True)
            created = True
            total = 0
            for info, name in zip(entries, names, strict=True):
                _check_ratio(info, path)
                relative = PurePosixPath(*name.parts[len(prefix) :]) if prefix else name
                file_path = target.joinpath(*relative.parts)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, file_path.open("wb") as output:
                    while chunk := source.read(_CHUNK):
                        total += len(chunk)
                        if total > MAX_TOTAL_BYTES:
                            raise ArchiveError(
                                f"{path.name} unpacks to more than {MAX_TOTAL_BYTES // 1024**3} GB."
                            )
                        output.write(chunk)
    except (ArchiveError, OSError, zipfile.BadZipFile, RuntimeError) as error:
        if created:  # only ever remove what this call made
            shutil.rmtree(target, ignore_errors=True)
        if isinstance(error, ArchiveError):
            raise
        raise ArchiveError(f"Could not unpack {path.name}: {error}") from error
    return target


def _is_model(info: zipfile.ZipInfo) -> bool:
    """Return whether an archive entry is a model file worth unpacking."""
    if info.is_dir():
        return False
    parts = PurePosixPath(info.filename.replace("\\", "/")).parts
    # Hidden names are skipped, but ".." is not hidden: it is refused by _safe_name.
    hidden = any(part.startswith(".") and part != ".." for part in parts)
    if not parts or hidden or "__MACOSX" in parts:
        return False
    return PurePosixPath(parts[-1]).suffix.casefold() in MODEL_SUFFIXES


def _safe_name(name: str, archive: Path) -> PurePosixPath:
    """Return an entry's path, refusing one that would land outside the target folder."""
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ArchiveError(f"{archive.name} has an unsafe file path ({name}); not unpacking it.")
    return path


def _shared_top_folder(names: list[PurePosixPath]) -> tuple[str, ...]:
    """Return the folders every model is in (``kit/files`` for a typical download), or ().

    Those levels are left out when unpacking, so the models start at the top
    of the unpacked folder.
    """
    folders = [name.parts[:-1] for name in names]
    shared: list[str] = []
    for level in zip(*folders, strict=False):
        if len(set(level)) != 1:
            break
        shared.append(level[0])
    return tuple(shared)


def _check_ratio(info: zipfile.ZipInfo, archive: Path) -> None:
    """Refuse an entry that expands far more than real model files do."""
    if info.file_size > _SMALL_FILE and info.file_size > MAX_RATIO * max(info.compress_size, 1):
        raise ArchiveError(
            f"{archive.name}: {info.filename} expands suspiciously much; not unpacking it."
        )
