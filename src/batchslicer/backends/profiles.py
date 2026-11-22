"""Locate a slicer's built-in (system) presets as plain JSON files.

Creality Print and older OrcaSlicer releases keep their built-in presets as JSON
under ``<data directory>/system/<vendor>/``. OrcaSlicer 2.4 and later instead
store them in packed ``<vendor>.opc`` files. For those, each needed vendor is
taken from the slicer program itself where possible (for an AppImage, using its
own ``--appimage-extract``): OrcaSlicer 2.4 ships the presets as JSON, 2.5 and
later as ``.opc`` files, which are unpacked to JSON (see
:mod:`batchslicer.backends.opc`). A vendor the program does not carry (2.5
ships only a few and downloads the rest) is unpacked from the ``.opc`` file in
the settings folder. The result is kept in a cache folder, rebuilt when the
slicer or those files change. This module does not interpret presets or modify
the slicer's data directory.
"""

import logging
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

from batchslicer.backends.opc import read_opc, unpack
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
        logger.info("Unpacking built-in presets for %s from %s", ", ".join(vendors), system)
        return _build_cache(
            _cache_key(executable, system), vendors, None, system, cache_directory, logger
        )
    return _extract_from_appimage(executable, vendors, system, cache_directory, logger)


def is_appimage(path: Path) -> bool:
    """Return whether ``path`` is a type 2 AppImage."""
    try:
        with path.open("rb") as file:
            file.seek(_APPIMAGE_MAGIC_OFFSET)
            return file.read(len(_APPIMAGE_MAGIC)) == _APPIMAGE_MAGIC
    except OSError:
        return False


def _installed_profiles(executable: Path) -> Path | None:
    """Return the profiles folder of a regular install or macOS app, if there is one."""
    base = executable.resolve().parent
    for candidate in (
        base / _BUNDLED_PROFILES,
        base.parent / _BUNDLED_PROFILES,
        base.parent / "Resources" / "profiles",  # a macOS app
        base.parent / "share" / "OrcaSlicer" / "profiles",
    ):
        if any(candidate.glob("*/machine/**/*.json")):
            return candidate
    return None


def _extract_from_appimage(
    executable: Path,
    vendors: list[str],
    system: Path,
    cache_directory: Path,
    logger: logging.Logger,
) -> Path:
    """Extract the vendors' presets from the AppImage, reusing an earlier extraction."""
    key = _cache_key(executable, system)
    target = cache_directory / key
    if (target / _COMPLETE_MARKER).is_file() and set(vendors) <= _cached_vendors(target):
        return target

    logger.info("Extracting built-in presets for %s from %s", ", ".join(vendors), executable)
    cache_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=cache_directory) as scratch:
        for vendor in vendors:
            try:
                subprocess.run(
                    (str(executable), "--appimage-extract", f"{_BUNDLED_PROFILES.as_posix()}/{vendor}*"),
                    cwd=scratch,
                    capture_output=True,
                    check=True,
                    timeout=_EXTRACT_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise PresetError(
                    f"Could not extract built-in presets from {executable}: {error}"
                ) from error
        bundled = Path(scratch) / "squashfs-root" / _BUNDLED_PROFILES
        return _build_cache(key, vendors, bundled, system, cache_directory, logger)


def _build_cache(
    key: str,
    vendors: list[str],
    bundled: Path | None,
    system: Path,
    cache_directory: Path,
    logger: logging.Logger,
) -> Path:
    """Gather each vendor's presets as JSON into ``cache_directory/key`` and return it.

    A vendor comes from ``bundled`` (the program's own presets) as JSON or as an
    ``.opc`` file, otherwise from the settings folder's ``.opc`` file.
    """
    target = cache_directory / key
    if (target / _COMPLETE_MARKER).is_file() and set(vendors) <= _cached_vendors(target):
        return target
    cache_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=cache_directory) as scratch:
        built = Path(scratch) / "profiles"
        built.mkdir()
        missing = []
        for vendor in vendors:
            source = bundled / vendor if bundled is not None else None
            packed = [
                path
                for path in (
                    bundled / f"{vendor}.opc" if bundled is not None else None,
                    system / f"{vendor}.opc",
                )
                if path is not None and path.is_file() and path.stat().st_size > 0
            ]
            if source is not None and _has_json_presets(source):
                shutil.copytree(source, built / vendor)
            elif packed:
                opc = read_opc(packed[0])
                if opc.name != vendor:
                    raise PresetError(f"{packed[0]} holds presets for '{opc.name}', not '{vendor}'.")
                logger.info("Unpacking %s presets %s from %s", vendor, opc.version, packed[0])
                unpack(opc, built)
            else:
                missing.append(vendor)
        if missing:
            where = f"{bundled.parent.parent.name} or {system}" if bundled is not None else str(system)
            raise PresetError(f"No built-in presets found for {', '.join(missing)} (looked in {where}).")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(built), target)
    (target / _COMPLETE_MARKER).write_text("\n".join(vendors), encoding="utf-8")
    return target


def _has_json_presets(folder: Path) -> bool:
    """Return whether ``folder`` holds a vendor's presets as JSON (not just its images)."""
    return any(folder.glob("*/**/*.json"))


def _cache_key(executable: Path, system: Path) -> str:
    """Return a cache folder name that changes when the slicer or its .opc files change."""
    stat = executable.stat()
    packed = sorted(
        f"{path.name}:{path.stat().st_size}:{int(path.stat().st_mtime)}" for path in system.glob("*.opc")
    )
    fingerprint = zlib.crc32("|".join(packed).encode("utf-8"))
    return f"{executable.stem}-{stat.st_size}-{int(stat.st_mtime)}-{fingerprint:08x}"


def _cached_vendors(target: Path) -> set[str]:
    """Return the vendors present in a cached extraction."""
    return {path.name for path in target.iterdir() if path.is_dir()}
