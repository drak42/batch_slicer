"""
OrcaBatch

Module:
    config.py

Purpose:
    Load and validate the application configuration.

Responsibilities:
    - Read YAML configuration
    - Validate required settings
    - Provide configuration values

Does NOT:
    - Modify configuration
    - Know about application logic
"""

from pathlib import Path
from typing import Any

import yaml


class Config:
    """
    Application configuration service.
    """

    def __init__(self, filename: Path):

        self.filename = filename

        self.data: dict[str, Any] = {}

    def load(self) -> None:
        """
        Load configuration from disk.
        """

        with self.filename.open(
            "r",
            encoding="utf-8"
        ) as stream:

            self.data = yaml.safe_load(stream)

    def get(self, *keys: str) -> Any:
        """
        Return a configuration value.

        Example:

            config.get("logging", "directory")
        """

        value: Any = self.data

        for key in keys:
            value = value[key]

        return value