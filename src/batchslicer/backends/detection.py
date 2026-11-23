"""Find installed slicers and their settings folders.

Looks for slicer AppImages in the folders people usually keep them in (and
for slicer programs on PATH), reads the version from the file name, and finds
the settings folder each slicer creates the first time it is opened. Stable
releases are recommended over pre-releases, newest first. On Windows it also
looks in Program Files, ``%LOCALAPPDATA%\\Programs`` and portable copies
unzipped into the usual folders, reads the version from the program's version
information (or its folder name), and finds the settings folder under
``%APPDATA%``. This module only looks; it does not write configuration or run
slicers. Flatpak installs are
not detected, because a Flatpak app is not a single program file.
"""

import os
import re
import shutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, ORCASLICER
from batchslicer.core.locations import is_windows

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
    """Settings folder under ~/.config (%APPDATA% on Windows); Creality Print adds a version subfolder."""

    versioned_data: bool = False
    windows_programs: tuple[str, ...] = ()
    """Where the Windows installer puts the program, below Program Files (wildcards allowed)."""


_SIGNATURES = {
    ORCASLICER.key: _SlicerSignature(
        ("orcaslicer",), ("orca-slicer",), "OrcaSlicer",
        windows_programs=("OrcaSlicer/orca-slicer.exe",),
    ),
    CREALITY_PRINT.key: _SlicerSignature(
        ("crealityprint", "creality_print"),
        ("CrealityPrint",),
        "Creality/Creality Print",
        versioned_data=True,
        windows_programs=("Creality/Creality Print*/CrealityPrint.exe", "Creality Print*/CrealityPrint.exe"),
    ),
    BAMBU_STUDIO.key: _SlicerSignature(
        ("bambustudio", "bambu_studio"), ("bambu-studio",), "BambuStudio",
        windows_programs=("Bambu Studio/bambu-studio.exe", "BambuStudio/bambu-studio.exe"),
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

    Stable releases come before pre-releases, copies with a known version
    before those without, then newer before older.
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
    if is_windows():
        for windows_program in _windows_programs(signature, home, environ):
            found.setdefault(windows_program.resolve(), _windows_installation(windows_program))
    return sorted(
        found.values(),
        # Stable before pre-release, a known version before an unknown one, then newest first.
        key=lambda item: (
            item.prerelease, not item.version, [-part for part in item.version], str(item.executable)
        ),
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
    environ = os.environ if environ is None else environ
    if is_windows():
        config_home = _app_data(home or Path.home(), environ)
    else:
        config_home = _config_home(home or Path.home(), environ)
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


def _windows_programs(
    signature: _SlicerSignature, home: Path, environ: Mapping[str, str]
) -> Iterable[Path]:
    """Yield the slicer's Windows programs: installed ones, and portable copies in the usual folders."""
    roots = [
        Path(value)
        for value in (
            environ.get("ProgramFiles", r"C:\Program Files"),
            environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            environ.get("LOCALAPPDATA", "") and str(Path(environ["LOCALAPPDATA"]) / "Programs"),
        )
        if value
    ]
    for root in roots:
        for pattern in signature.windows_programs:
            yield from (path for path in root.glob(pattern) if path.is_file())
    names = {f"{name}.exe".casefold() for name in signature.program_names}
    for folder in (home / name for name in SEARCH_FOLDERS):
        for pattern in ("*.exe", "*/*.exe", "*/*/*.exe"):
            try:
                yield from (path for path in folder.glob(pattern) if path.name.casefold() in names)
            except OSError:
                continue


def _windows_installation(program: Path) -> Installation:
    """Return an Installation, its version from the program's version information or folder names."""
    version = _file_version(program)
    names = " ".join(part for part in (program.parent.name, program.parent.parent.name))
    return Installation(
        executable=program,
        version=version or _parse_version(program.parent.name) or _parse_version(names),
        prerelease=bool(_PRERELEASE_PATTERN.search(names)),
    )


def _file_version(program: Path) -> tuple[int, ...]:
    """Return a Windows program's file version (from its version resource), or ()."""
    if sys.platform != "win32":
        return ()
    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.WinDLL("version")
        size = version_dll.GetFileVersionInfoSizeW(str(program), None)
        if not size:
            return ()
        buffer = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(str(program), 0, size, buffer):
            return ()
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ()
        words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
        major, minor = words[4] >> 16, words[4] & 0xFFFF
        patch, build = words[5] >> 16, words[5] & 0xFFFF
        return (major, minor, patch, build) if build else (major, minor, patch)
    except (OSError, AttributeError, ValueError):
        return ()


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


def _app_data(home: Path, environ: Mapping[str, str]) -> Path:
    """Return %APPDATA% (where Windows programs keep their settings), or ~/AppData/Roaming."""
    value = environ.get("APPDATA", "")
    return Path(value) if value and Path(value).is_absolute() else home / "AppData" / "Roaming"


def _config_home(home: Path, environ: Mapping[str, str]) -> Path:
    """Return XDG_CONFIG_HOME, or ~/.config."""
    value = environ.get("XDG_CONFIG_HOME", "")
    return Path(value) if value and Path(value).is_absolute() else home / ".config"
