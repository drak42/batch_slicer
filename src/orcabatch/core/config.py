"""Load and validate the application configuration."""

from pathlib import Path
from typing import Any

import yaml


class Config:
    """Application configuration service."""

    def __init__(self, filename: Path) -> None:
        """Store the configuration file path."""
        self.filename = filename
        self.data: dict[str, Any] = {}

    def load(self) -> None:
        """Load configuration data from disk."""
        with self.filename.open("r", encoding="utf-8") as stream:
            self.data = yaml.safe_load(stream)

    def get(self, *keys: str) -> Any:
        """Return a configuration value addressed by nested keys."""
        value: Any = self.data
        for key in keys:
            value = value[key]
        return value
