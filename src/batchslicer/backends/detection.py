"""Find installed slicers and their settings folders.

Looks for slicer AppImages in the folders people usually keep them in (and
for slicer programs on PATH), reads the version from the file name, and finds
the settings folder each slicer creates the first time it is opened. Stable
releases are recommended over pre-releases, newest first. On Windows it also
looks in Program Files, ``%LOCALAPPDATA%\\Programs`` and portable copies
unzipped into the usual folders, reads the version from Windows' list of
installed programs (or else the program's version information or its folder
name), and finds the settings folder under
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
from pathlib import Path, PureWindowsPath
from typing import Any

from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, ORCASLICER
from batchslicer.core.locations import is_windows

SEARCH_FOLDERS = ("Apps", "Applications", "AppImages", "Downloads", "Desktop", ".local/bin")
"""Folders under the home folder searched for AppImages."""

_SYSTEM_FOLDERS = (Path("/opt"),)
_VERSION_PATTERN = re.compile(r"[vV]?(\d+(?:\.\d+)+)")
_VERSION_FOLDER = re.compile(r"\d+(?:\.\d+)+")
"""A Creality Print settings folder name, such as 7.3."""
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

    # Only folders named just a version: Creality Print 7.3 also leaves
    # ".7.3.staging-<number>" and ".migration-7.3" folders while it moves settings.
    versions = sorted(
        (path for path in base.glob("*") if path.is_dir() and _VERSION_FOLDER.fullmatch(path.name)),
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
    """Return an Installation with the program's version.

    The version comes from the list of installed programs, then the program's
    version information, then its folder names. Installed programs come first
    because some slicers carry a placeholder in their version information
    (OrcaSlicer 2.5 says 2.0.0.0, Creality Print 7.x says 7.0.0.0).
    """
    names = " ".join(part for part in (program.parent.name, program.parent.parent.name))
    version = (
        _installed_version(program, _uninstall_entries())
        or _file_version(program)
        or _parse_version(program.parent.name)
        or _parse_version(names)
    )
    return Installation(
        executable=program,
        version=version,
        prerelease=bool(_PRERELEASE_PATTERN.search(names)),
    )


def _installed_version(program: Path, entries: Iterable[tuple[str, str]]) -> tuple[int, ...]:
    """Return the version Windows lists for the program's install folder, or ().

    ``entries`` are (install folder, version) pairs from the installed-programs
    list. A slicer that updates itself in place may leave an older version
    there; it is still closer than a placeholder in the program file.
    """
    folder = _folder_key(str(program.parent))
    for location, version in entries:
        if location and _folder_key(location) == folder:
            parsed = _parse_version(version)
            if parsed:
                return parsed
    return ()


def _folder_key(text: str) -> str:
    """Return a folder path in a form that compares equal however Windows wrote it."""
    return text.strip().strip('"').rstrip("\\/").replace("/", "\\").casefold()


def _uninstall_entries() -> list[tuple[str, str]]:
    """Return (install folder, version) for each program in Windows' installed-programs list.

    The install folder is InstallLocation, or else the folder of the
    uninstaller. Returns [] on other systems or when the list cannot be read.
    """
    if sys.platform != "win32":
        return []
    import winreg

    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    entries: list[tuple[str, str]] = []
    for root, path in keys:
        try:
            parent = winreg.OpenKey(root, path)
        except OSError:
            continue
        with parent:
            for index in range(winreg.QueryInfoKey(parent)[0]):
                try:
                    with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                        version = _registry_text(winreg, entry, "DisplayVersion")
                        location = _registry_text(winreg, entry, "InstallLocation") or (
                            _uninstaller_folder(_registry_text(winreg, entry, "UninstallString"))
                        )
                except OSError:
                    continue
                if version and location:
                    entries.append((location, version))
    return entries


def _registry_text(winreg: Any, key: Any, name: str) -> str:
    """Return a registry value as text, or "" when the key does not have it."""
    try:
        return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


def _uninstaller_folder(command: str) -> str:
    """Return the folder of the program an UninstallString runs, or ""."""
    command = command.strip()
    program = command[1:].split('"', 1)[0] if command.startswith('"') else command.split(" /", 1)[0]
    return str(PureWindowsPath(program).parent) if program else ""


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
