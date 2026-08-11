"""
OrcaBatch

Module:
    app.py

Purpose:
    Bootstrap the OrcaBatch application.

Responsibilities:
    - Load configuration
    - Configure logging
    - Display startup banner
    - Verify startup environment

This module coordinates startup only.
It does not contain application logic.
"""

from pathlib import Path

from .banner import create_banner
from .core.config import Config
from .core.logging import configure_logging


class Application:
    """
    OrcaBatch application.
    """

    def __init__(self) -> None:

        self.config = Config(
            Path("config/config.yaml")
        )

    def run(self) -> int:

        self.config.load()

        logger = configure_logging(
            Path(
                self.config.get(
                    "logging",
                    "directory"
                )
            )
        )

        print(create_banner())

        logger.info("Application started.")

        return 0