"""Locate a slicer's built-in (system) presets as plain JSON files.

Creality Print and older OrcaSlicer releases keep their built-in presets as JSON
under ``<data directory>/system/<vendor>/``. OrcaSlicer 2.4 instead stores them
in packed ``<vendor>.opc`` files, an internal format that is not read here.
The same presets ship as JSON inside the slicer program, so for an AppImage the
needed vendors are extracted (using the AppImage's own ``--appimage-extract``)
into a cache folder, once per slicer version. This module does not interpret
presets or modify the slicer's data directory.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from batchslicer.backends.presets import PresetError
from batchslicer.core.logging import get_logger

_APPIMAGE_MAGIC = b"AI\x02"
_APPIMAGE_MAGIC_OFFSET = 8
_BUNDLED_PROFILES = Path("resources") / "profiles"
_COMPLETE_MARKER = ".complete"
_EXTRACT_TIMEOUT_SECONDS = 300


def find_system_profiles(
    executable: Path,
    data_directory: Path,
    cache_directory: Path,
    *,
    logger: logging.Logger | None = None,
) -> Path:
    """Return a folder holding the slicer's built-in presets as ``<vendor>/<kind>/*.json``.

    Raises :class:`PresetError` if no usable built-in presets can be found.
    """
    logger = logger or get_logger()
    system = data_directory / "system"
    if any(system.glob("*/machine/**/*.json")):
        return system

    vendors = sorted(path.stem for path in system.glob("*.opc"))
    if not vendors:
        raise PresetError(f"No built-in presets found in {system}.")

    installed = _installed_profiles(executable)
    if installed is not None:
        return installed
    if not is_appimage(executable):
        raise PresetError(
            f"Cannot find the built-in presets for {executable}; "
            "expected an AppImage or a resources/profiles folder next to it."
        )
    return _extract_from_appimage(executable, vendors, cache_directory, logger)


def is_appimage(path: Path) -> bool:
    """Return whether ``path`` is a type 2 AppImage."""
    try:
        with path.open("rb") as file:
            file.seek(_APPIMAGE_MAGIC_OFFSET)
            return file.read(len(_APPIMAGE_MAGIC)) == _APPIMAGE_MAGIC
    except OSError:
        return False


def _installed_profiles(executable: Path) -> Path | None:
    """Return the profiles folder of a non-AppImage installation, if there is one."""
    base = executable.resolve().parent
    for candidate in (
        base / _BUNDLED_PROFILES,
        base.parent / _BUNDLED_PROFILES,
        base.parent / "share" / "OrcaSlicer" / "profiles",
    ):
        if any(candidate.glob("*/machine/**/*.json")):
            return candidate
    return None


def _extract_from_appimage(
    executable: Path,
    vendors: list[str],
    cache_directory: Path,
    logger: logging.Logger,
) -> Path:
    """Extract the vendors' presets from the AppImage, reusing an earlier extraction."""
    stat = executable.stat()
    key = f"{executable.stem}-{stat.st_size}-{int(stat.st_mtime)}"
    target = cache_directory / key
    wanted = set(vendors)
    if (target / _COMPLETE_MARKER).is_file() and wanted <= _cached_vendors(target):
        return target

    logger.info("Extracting built-in presets for %s from %s", ", ".join(vendors), executable)
    cache_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=cache_directory) as scratch:
        for vendor in vendors:
            try:
                subprocess.run(
                    (str(executable), "--appimage-extract", f"{_BUNDLED_PROFILES}/{vendor}*"),
                    cwd=scratch,
                    capture_output=True,
                    check=True,
                    timeout=_EXTRACT_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise PresetError(
                    f"Could not extract built-in presets from {executable}: {error}"
                ) from error

        extracted = Path(scratch) / "squashfs-root" / _BUNDLED_PROFILES
        missing = [vendor for vendor in vendors if not (extracted / vendor).is_dir()]
        if missing:
            raise PresetError(
                f"{executable} does not contain built-in presets for: {', '.join(missing)}"
            )
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(extracted), target)
    (target / _COMPLETE_MARKER).write_text("\n".join(vendors), encoding="utf-8")
    return target


def _cached_vendors(target: Path) -> set[str]:
    """Return the vendors present in a cached extraction."""
    return {path.name for path in target.iterdir() if path.is_dir()}
