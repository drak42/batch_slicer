"""Find installed slicers and their settings folders.

Looks for slicer AppImages in the folders people usually keep them in (and
for slicer programs on PATH), reads the version from the file name, and finds
the settings folder each slicer creates the first time it is opened. Stable
releases are recommended over pre-releases, newest first. This module only
looks; it does not write configuration or run slicers. Flatpak installs are
not detected, because a Flatpak app is not a single program file.
"""

import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, ORCASLICER

SEARCH_FOLDERS = ("Apps", "Applications", "AppImages", "Downloads", "Desktop", ".local/bin")
"""Folders under the home folder searched for AppImages."""

_SYSTEM_FOLDERS = (Path("/opt"),)
_VERSION_PATTERN = re.compile(r"[vV]?(\d+(?:\.\d+)+)")
_PRERELEASE_PATTERN = re.compile(r"alpha|beta|[-_.]rc\d*|nightly|dev", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _SlicerSignature:
    """How one slicer's program files and settings folder are named."""

    file_prefixes: tuple[str, ...]
    program_names: tuple[str, ...]
    data_directory: str
    """Settings folder under ~/.config; Creality Print adds a version subfolder."""

    versioned_data: bool = False


_SIGNATURES = {
    ORCASLICER.key: _SlicerSignature(("orcaslicer",), ("orca-slicer",), "OrcaSlicer"),
    CREALITY_PRINT.key: _SlicerSignature(
        ("crealityprint", "creality_print"),
        ("CrealityPrint",),
        "Creality/Creality Print",
        versioned_data=True,
    ),
    BAMBU_STUDIO.key: _SlicerSignature(
        ("bambustudio", "bambu_studio"), ("bambu-studio",), "BambuStudio"
    ),
}


@dataclass(frozen=True, slots=True)
class Installation:
    """One installed copy of a slicer program."""

    executable: Path
    version: tuple[int, ...]
    prerelease: bool

    @property
    def version_text(self) -> str:
        """Return the version as dotted text, or "unknown"."""
        return ".".join(str(part) for part in self.version) if self.version else "unknown"


def find_installations(
    slicer_key: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[Installation]:
    """Return installed copies of a slicer, the recommended one first.

    Stable releases come before pre-releases, then newer before older.
    """
    signature = _SIGNATURES[slicer_key]
    home = home or Path.home()
    environ = os.environ if environ is None else environ
    folders = [home / name for name in SEARCH_FOLDERS] + list(_SYSTEM_FOLDERS)

    found: dict[Path, Installation] = {}
    for candidate in _appimages(folders):
        if _matches(candidate.name, signature.file_prefixes):
            found.setdefault(candidate.resolve(), _installation(candidate))
    for name in signature.program_names:
        program = shutil.which(name, path=environ.get("PATH", ""))
        if program:
            found.setdefault(Path(program).resolve(), _installation(Path(program)))
    return sorted(
        found.values(),
        key=lambda item: (item.prerelease, [-part for part in item.version], str(item.executable)),
    )


def find_data_directory(
    slicer_key: str,
    installation: Installation | None = None,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the slicer's settings folder, or None if it has never been opened.

    For Creality Print, which keeps one folder per version, the folder matching
    the installation's major.minor version is preferred, then the newest.
    """
    signature = _SIGNATURES[slicer_key]
    config_home = _config_home(home or Path.home(), os.environ if environ is None else environ)
    base = config_home / signature.data_directory
    if not signature.versioned_data:
        return base if base.is_dir() else None

    versions = sorted(
        (path for path in base.glob("*") if path.is_dir() and _parse_version(path.name)),
        key=lambda path: _parse_version(path.name),
        reverse=True,
    )
    if installation is not None and len(installation.version) >= 2:
        wanted = installation.version[:2]
        for path in versions:
            if _parse_version(path.name)[:2] == wanted:
                return path
    return versions[0] if versions else None


def _appimages(folders: Iterable[Path]) -> Iterable[Path]:
    """Yield AppImage files directly inside, or one level below, ``folders``."""
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() == ".appimage":
                yield entry
            elif entry.is_dir() and not entry.name.startswith("."):
                try:
                    yield from (
                        child
                        for child in entry.iterdir()
                        if child.is_file() and child.suffix.lower() == ".appimage"
                    )
                except OSError:
                    continue


def _matches(name: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether a file name starts with one of ``prefixes``, ignoring case and separators."""
    simplified = name.casefold().replace("-", "").replace(" ", "")
    return any(simplified.startswith(prefix.replace("-", "")) for prefix in prefixes)


def _installation(path: Path) -> Installation:
    """Return an Installation with the version read from the file name."""
    return Installation(
        executable=path,
        version=_parse_version(path.name),
        prerelease=bool(_PRERELEASE_PATTERN.search(path.name)),
    )


def _parse_version(text: str) -> tuple[int, ...]:
    """Return the first dotted version number in ``text`` as integers, or ()."""
    match = _VERSION_PATTERN.search(text)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def _config_home(home: Path, environ: Mapping[str, str]) -> Path:
    """Return XDG_CONFIG_HOME, or ~/.config."""
    value = environ.get("XDG_CONFIG_HOME", "")
    return Path(value) if value and Path(value).is_absolute() else home / ".config"
