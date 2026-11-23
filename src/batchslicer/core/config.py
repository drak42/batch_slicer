"""Find, load and access BatchSlicer application configuration.

This module provides the sole configuration access path. It finds the
configuration file, reads YAML safely, caches loaded data, and turns path
settings into absolute paths: ``~`` is expanded, relative paths are taken
relative to the configuration file's folder, and missing ``paths`` settings
fall back to the standard per-user locations. It can also render a new
configuration file (used by ``batchslicer setup``). It does not edit existing
configuration or check that configured paths exist.
"""

import os
import shutil
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from batchslicer.core.locations import (
    CONFIG_ENVIRONMENT_VARIABLE,
    PROJECT_CONFIG,
    default_paths,
    user_config_file,
)


class Config:
    """Load and access one BatchSlicer configuration file."""

    def __init__(self, path: Path) -> None:
        """Store the path to the configuration file."""
        self._path = path
        self._data: dict[str, Any] | None = None

    @property
    def path(self) -> Path:
        """Return the configuration file's path."""
        return self._path

    def load(self) -> None:
        """Load and cache YAML configuration from the configured path."""
        if not self._path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {self._path}")

        try:
            with self._path.open("r", encoding="utf-8") as configuration_file:
                data = yaml.safe_load(configuration_file)
        except yaml.YAMLError as error:
            hint = ""
            if "escape" in str(error):
                hint = (
                    " A backslash in double quotes starts an escape: write Windows paths "
                    "with forward slashes (C:/Program Files/...) or in single quotes."
                )
            raise ValueError(f"Invalid YAML configuration: {self._path}.{hint}") from error

        if not isinstance(data, dict):
            raise ValueError(f"Configuration root must be a mapping: {self._path}")

        self._data = data

    def get(self, section: str, key: str) -> Any:
        """Return a required configuration value by section and key."""
        data = self._get_data()
        section_data = data[section]
        if not isinstance(section_data, dict):
            raise KeyError(section)
        return section_data[key]

    def section(self, section: str) -> Any:
        """Return a whole configuration section as written, or ``None`` if it is missing."""
        return self._get_data().get(section)

    def has(self, section: str, key: str) -> bool:
        """Return whether a configuration section contains the requested key."""
        data = self._get_data()
        section_data = data.get(section)
        return isinstance(section_data, dict) and key in section_data

    def get_path(self, section: str, key: str) -> Path:
        """Return a configured path as an absolute path.

        ``~`` is expanded and relative paths are taken relative to the folder
        holding the configuration file. A ``paths`` setting that is missing or
        empty falls back to its standard per-user location; any other missing
        or empty path raises ``KeyError`` or ``ValueError``.
        """
        if section == "paths" and not self._has_value(section, key):
            defaults = default_paths()
            if key not in defaults:
                raise KeyError(key)
            return defaults[key]

        value = self.get(section, key)
        if isinstance(value, Path):
            path = value
        elif isinstance(value, str) and value:
            path = Path(value)
        else:
            raise ValueError(f"Configuration value {section}.{key} must not be empty.")
        path = path.expanduser()
        if not path.is_absolute():
            # resolve() tidies "config/../output" into its plain form.
            path = (self._path.absolute().parent / path).resolve()
        return path

    def get_program(self, section: str, key: str = "executable") -> Path:
        """Return a configured program path.

        A bare program name (no folder, such as ``orca-slicer``) is looked up on
        PATH and returned unchanged if not found there; anything else is
        resolved like :meth:`get_path`.
        """
        value = self.get(section, key)
        if isinstance(value, str) and value and not value.startswith("~"):
            if len(Path(value).parts) == 1:
                found = shutil.which(value)
                return Path(found) if found else Path(value)
        return self.get_path(section, key)

    def _has_value(self, section: str, key: str) -> bool:
        """Return whether ``section.key`` is set to a non-empty value."""
        return self.has(section, key) and self.get(section, key) not in (None, "")

    def _get_data(self) -> dict[str, Any]:
        """Return cached configuration data, loading it on first access."""
        if self._data is None:
            self.load()
        assert self._data is not None  # load() either sets the data or raises
        return self._data


def find_config_file(
    explicit: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the configuration file to use.

    In order: ``explicit`` (from ``--config``), the ``BATCHSLICER_CONFIG``
    environment variable, ``config/config.yaml`` in the current folder (a
    project checkout), then the per-user ``~/.config/batchslicer/config.yaml``.
    The first two are returned even if missing so the error names them.
    Raises ``FileNotFoundError`` listing where it looked if none exists.
    """
    environ = os.environ if environ is None else environ
    if explicit is not None:
        return explicit.expanduser()
    from_environment = environ.get(CONFIG_ENVIRONMENT_VARIABLE, "")
    if from_environment:
        return Path(from_environment).expanduser()

    candidates = (PROJECT_CONFIG, user_config_file(environ))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = " or ".join(str(candidate.absolute()) for candidate in candidates)
    raise FileNotFoundError(
        f"No configuration file found (looked for {searched}). "
        "Run 'batchslicer setup' to create one, or pass --config PATH."
    )


@lru_cache(maxsize=4)
def get_config(path: Path | None = None) -> Config:
    """Return the loaded Config for ``path``, or for the file found by find_config_file."""
    config = Config(path if path is not None else find_config_file())
    config.load()
    return config


_SLICER_SECTIONS = ("orca", "creality_print", "bambu_studio")


def render_config(
    slicers: Mapping[str, tuple[Path, Path]],
    *,
    home: Path | None = None,
    printers: Mapping[str, Any] | None = None,
) -> str:
    """Return the text of a new configuration file.

    ``slicers`` maps slicer sections to ``(executable, datadir)``; slicers not
    included are written with empty paths. Paths inside ``home`` are written
    with ``~``. The ``paths`` settings are left empty so the defaults apply.
    ``printers`` (kept from an earlier file) is written as given; without it
    the section is shown as a commented example.
    """
    home = home or Path.home()

    def show(path: Path) -> str:
        # Forward slashes on every system: Windows accepts them, and they need no
        # escaping inside YAML's double quotes.
        try:
            text = "~/" + path.relative_to(home).as_posix()
        except ValueError:
            text = path.as_posix()
        return text.replace("\\", "\\\\").replace('"', '\\"')

    lines = [
        "# BatchSlicer configuration, created by `batchslicer setup`.",
        "# Paths may start with ~ for your home folder; relative paths are",
        "# relative to the folder this file is in.",
        "",
        "# Slicers: executable is the slicer program, datadir is the folder where it",
        "# keeps its settings and presets. Leave both empty for a slicer you don't use.",
    ]
    for section in _SLICER_SECTIONS:
        executable, datadir = slicers.get(section, (None, None))
        lines += [
            f"{section}:",
            f'  executable: "{show(executable) if executable else ""}"',
            f'  datadir: "{show(datadir) if datadir else ""}"',
            "",
        ]
    lines += [
        "# Folders. Leave empty to use the defaults shown.",
        "paths:",
        '  incoming: ""       # models offered for slicing   (default ~/BatchSlicer/incoming)',
        '  output: ""         # default output folder        (default ~/BatchSlicer/output)',
        '  logs: ""           # log files                    (default ~/.local/state/batchslicer)',
        '  data: ""           # BatchSlicer\'s working cache  (default ~/.cache/batchslicer)',
        '  profiles: ""       # saved profiles file          '
        "(default ~/.local/share/batchslicer/profiles.yaml)",
        "",
        *PRINTERS_COMMENT,
    ]
    if printers:
        lines += [yaml.safe_dump({"printers": dict(printers)}, sort_keys=False, allow_unicode=True)]
    else:
        lines += [
            "# printers:",
            "#   k2plus:",
            '#     url: "http://192.168.1.50:7125"',
            '#     api_key: ""',
            "#   ender3:",
            '#     type: octoprint',
            '#     url: "http://octopi.local"',
            '#     api_key: "paste the key from OctoPrint here"',
            "",
        ]
    return "\n".join(lines)


PRINTERS_COMMENT = (
    "# Printers to send G-code to with --send NAME (--send also takes an address",
    "# such as 192.168.1.50 directly): Klipper printers running Moonraker, or",
    "# OctoPrint with type: octoprint. url is the address (Moonraker usually uses",
    "# port 7125); api_key is only needed if Moonraker asks for one, and OctoPrint",
    "# always needs one (Settings > Application Keys).",
)
