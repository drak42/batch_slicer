"""Name the standard per-user locations BatchSlicer uses.

On Linux, locations follow the XDG Base Directory conventions: settings under
``~/.config``, saved profiles under ``~/.local/share``, logs under
``~/.local/state`` and caches under ``~/.cache``, each honouring its ``XDG_*``
environment variable. On Windows, settings and profiles go under
``%APPDATA%\\BatchSlicer`` and logs and caches under ``%LOCALAPPDATA%\\BatchSlicer``.
On macOS, settings and profiles go under
``~/Library/Application Support/BatchSlicer``, logs under
``~/Library/Logs/BatchSlicer`` and caches under ``~/Library/Caches/BatchSlicer``.
An ``XDG_*`` variable, when set, still wins on every system. Models and
results go in a visible ``~/BatchSlicer`` folder because users work with them
directly. This module only names locations; it does not create folders or read
configuration.
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "batchslicer"
CONFIG_FILE_NAME = "config.yaml"
CONFIG_ENVIRONMENT_VARIABLE = "BATCHSLICER_CONFIG"
PROJECT_CONFIG = Path("config") / CONFIG_FILE_NAME
"""Configuration inside a project checkout, relative to the current folder."""

_NATIVE_NAME = "BatchSlicer"
"""The folder name under AppData (Windows) and ~/Library (macOS), as programs there name theirs."""


def is_windows() -> bool:
    """Return whether BatchSlicer is running on Windows."""
    return os.name == "nt"


def is_macos() -> bool:
    """Return whether BatchSlicer is running on macOS."""
    return sys.platform == "darwin"


@dataclass(frozen=True)
class _Kind:
    """Where one kind of file goes on each system."""

    xdg_variable: str
    linux: Path
    """Below the home folder, before ``batchslicer``."""
    windows_variable: str
    """APPDATA or LOCALAPPDATA."""
    mac: str
    """The folder in ~/Library."""
    windows_subfolder: str = ""


_SETTINGS = _Kind("XDG_CONFIG_HOME", Path(".config"), "APPDATA", "Application Support")
_PROFILES = _Kind("XDG_DATA_HOME", Path(".local") / "share", "APPDATA", "Application Support")
_LOGS = _Kind("XDG_STATE_HOME", Path(".local") / "state", "LOCALAPPDATA", "Logs", "logs")
_CACHE = _Kind("XDG_CACHE_HOME", Path(".cache"), "LOCALAPPDATA", "Caches", "cache")


def user_config_file(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-user configuration file.

    ``~/.config/batchslicer/config.yaml`` on Linux,
    ``%APPDATA%\\BatchSlicer\\config.yaml`` on Windows and
    ``~/Library/Application Support/BatchSlicer/config.yaml`` on macOS.
    """
    return _folder(_SETTINGS, environ) / CONFIG_FILE_NAME


def default_paths(environ: Mapping[str, str] | None = None) -> dict[str, Path]:
    """Return the default location of each ``paths`` setting."""
    home = Path.home()
    return {
        "incoming": home / "BatchSlicer" / "incoming",
        "output": home / "BatchSlicer" / "output",
        "logs": _folder(_LOGS, environ),
        "data": _folder(_CACHE, environ),
        "profiles": _folder(_PROFILES, environ) / "profiles.yaml",
    }


def _folder(kind: _Kind, environ: Mapping[str, str] | None) -> Path:
    """Return BatchSlicer's folder for one kind of file.

    The ``XDG_*`` variable wins when set to an absolute path (per the XDG
    specification, a relative value is ignored). Otherwise Windows uses
    ``%APPDATA%`` or ``%LOCALAPPDATA%``, macOS ``~/Library``, and Linux the
    XDG default under the home folder.
    """
    values = os.environ if environ is None else environ
    xdg = values.get(kind.xdg_variable, "")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    if is_windows():
        base = values.get(kind.windows_variable, "")
        folder = Path(base) if base and Path(base).is_absolute() else Path.home() / "AppData" / (
            "Roaming" if kind.windows_variable == "APPDATA" else "Local"
        )
        folder = folder / _NATIVE_NAME
        return folder / kind.windows_subfolder if kind.windows_subfolder else folder
    if is_macos():
        return Path.home() / "Library" / kind.mac / _NATIVE_NAME
    return Path.home() / kind.linux / APP_NAME
