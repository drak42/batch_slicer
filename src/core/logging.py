"""
OrcaBatch

Module:
    logging.py

Purpose:
    Configure the application's logging system.

Responsibilities:
    - Configure logging
    - Create log directory
    - Provide application logger

Does NOT:
    - Write application logic
    - Manage log retention
"""

from pathlib import Path
import logging


LOGGER_NAME = "orcabatch"


def configure_logging(log_directory: Path) -> logging.Logger:
    """
    Configure the application logger.

    Args:
        log_directory:
            Directory used to store log files.

    Returns:
        Configured logger.
    """

    log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)

    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logfile = logging.FileHandler(
        log_directory / "orcabatch.log"
    )

    logfile.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(logfile)

    return logger