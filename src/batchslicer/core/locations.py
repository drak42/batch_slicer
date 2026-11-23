"""Name the standard per-user locations BatchSlicer uses.

On Linux, locations follow the XDG Base Directory conventions: settings under
``~/.config``, saved profiles under ``~/.local/share``, logs under
``~/.local/state`` and caches under ``~/.cache``, each honouring its ``XDG_*``
environment variable. On Windows, settings and profiles go under
``%APPDATA%\BatchSlicer`` and logs and caches under ``%LOCALAPPDATA%\BatchSlicer``
(an ``XDG_*`` variable, when set, still wins). Models and results go in a
visible ``~/BatchSlicer`` folder because users work with them directly. This
module only names locations; it does not create folders or read configuration.
"""

import os
from collections.abc import Mapping
from pathlib import Path

APP_NAME = "batchslicer"
CONFIG_FILE_NAME = "config.yaml"
CONFIG_ENVIRONMENT_VARIABLE = "BATCHSLICER_CONFIG"
PROJECT_CONFIG = Path("config") / CONFIG_FILE_NAME
"""Configuration inside a project checkout, relative to the current folder."""


_WINDOWS_NAME = "BatchSlicer"
"""The folder name under %APPDATA% and %LOCALAPPDATA%, as Windows programs name theirs."""


def is_windows() -> bool:
    """Return whether BatchSlicer is running on Windows."""
    return os.name == "nt"


def user_config_file(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-user configuration file.

    ``~/.config/batchslicer/config.yaml`` on Linux,
    ``%APPDATA%\\BatchSlicer\\config.yaml`` on Windows.
    """
    return _folder("XDG_CONFIG_HOME", Path(".config"), "APPDATA", environ) / CONFIG_FILE_NAME


def default_paths(environ: Mapping[str, str] | None = None) -> dict[str, Path]:
    """Return the default location of each ``paths`` setting."""
    home = Path.home()
    return {
        "incoming": home / "BatchSlicer" / "incoming",
        "output": home / "BatchSlicer" / "output",
        "logs": _folder("XDG_STATE_HOME", Path(".local") / "state", "LOCALAPPDATA", environ, "logs"),
        "data": _folder("XDG_CACHE_HOME", Path(".cache"), "LOCALAPPDATA", environ, "cache"),
        "profiles": _folder("XDG_DATA_HOME", Path(".local") / "share", "APPDATA", environ)
        / "profiles.yaml",
    }


def _folder(
    variable: str,
    fallback: Path,
    windows_variable: str,
    environ: Mapping[str, str] | None,
    windows_subfolder: str = "",
) -> Path:
    """Return BatchSlicer's folder for one kind of file.

    The ``XDG_*`` ``variable`` wins when set; otherwise Windows uses
    ``%windows_variable%\\BatchSlicer`` (plus ``windows_subfolder``) and
    Linux ``~/<fallback>/batchslicer``.
    """
    values = os.environ if environ is None else environ
    xdg = values.get(variable, "")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / APP_NAME
    if is_windows():
        base = values.get(windows_variable, "")
        folder = Path(base) if base and Path(base).is_absolute() else Path.home() / "AppData" / (
            "Roaming" if windows_variable == "APPDATA" else "Local"
        )
        folder = folder / _WINDOWS_NAME
        return folder / windows_subfolder if windows_subfolder else folder
    return Path.home() / fallback / APP_NAME
