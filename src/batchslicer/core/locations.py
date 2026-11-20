"""Name the standard per-user locations BatchSlicer uses.

Locations follow the XDG Base Directory conventions used on Linux: settings
under ``~/.config``, logs under ``~/.local/state`` and caches under ``~/.cache``,
each honouring its ``XDG_*`` environment variable. Models and results go in a
visible ``~/BatchSlicer`` folder because users work with them directly. This
module only names locations; it does not create folders or read configuration.
"""

from collections.abc import Mapping
import os
from pathlib import Path


APP_NAME = "batchslicer"
CONFIG_FILE_NAME = "config.yaml"
CONFIG_ENVIRONMENT_VARIABLE = "BATCHSLICER_CONFIG"
PROJECT_CONFIG = Path("config") / CONFIG_FILE_NAME
"""Configuration inside a project checkout, relative to the current folder."""


def user_config_file(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-user configuration file, ``~/.config/batchslicer/config.yaml``."""
    return _base("XDG_CONFIG_HOME", Path(".config"), environ) / APP_NAME / CONFIG_FILE_NAME


def default_paths(environ: Mapping[str, str] | None = None) -> dict[str, Path]:
    """Return the default location of each ``paths`` setting."""
    home = Path.home()
    return {
        "incoming": home / "BatchSlicer" / "incoming",
        "output": home / "BatchSlicer" / "output",
        "logs": _base("XDG_STATE_HOME", Path(".local") / "state", environ) / APP_NAME,
        "data": _base("XDG_CACHE_HOME", Path(".cache"), environ) / APP_NAME,
    }


def _base(variable: str, fallback: Path, environ: Mapping[str, str] | None) -> Path:
    """Return the XDG base folder in ``variable``, or ``~/<fallback>``.

    Per the XDG specification, a relative value is ignored.
    """
    value = (os.environ if environ is None else environ).get(variable, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback
