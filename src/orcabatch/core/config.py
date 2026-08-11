"""Load and access OrcaBatch application configuration.

This module provides the sole configuration access path. It reads YAML safely,
caches loaded data, and validates configured Orca paths. It does not provide
defaults, edit configuration, or read environment variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


class Config:
    """Load, access, and validate one OrcaBatch configuration file."""

    def __init__(self, path: Path = Path("config/config.yaml")) -> None:
        """Store the path to the configuration file."""
        self._path = path
        self._data: dict[str, Any] | None = None

    def load(self) -> None:
        """Load and cache YAML configuration from the configured path."""
        if not self._path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {self._path}")

        try:
            with self._path.open("r", encoding="utf-8") as configuration_file:
                data = yaml.safe_load(configuration_file)
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid YAML configuration: {self._path}") from error

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

    def has(self, section: str, key: str) -> bool:
        """Return whether a configuration section contains the requested key."""
        data = self._get_data()
        section_data = data.get(section)
        return isinstance(section_data, dict) and key in section_data

    def validate(self) -> None:
        """Verify that the configured Orca executable and data directory exist."""
        for key in ("executable", "datadir"):
            value = self.get("orca", key)
            if not isinstance(value, str) or not value or not Path(value).exists():
                raise FileNotFoundError(f"Configured Orca path not found: {value}")

    def _get_data(self) -> dict[str, Any]:
        """Return cached configuration data, loading it on first access."""
        if self._data is None:
            self.load()
        return self._data


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the cached Config instance for config/config.yaml."""
    config = Config()
    config.load()
    return config
