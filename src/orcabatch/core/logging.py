"""Configure the application's logging system."""

import logging
from pathlib import Path


LOGGER_NAME = "orcabatch"


def configure_logging(log_directory: Path) -> logging.Logger:
    """Configure and return the application logger."""
    log_directory.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logfile = logging.FileHandler(log_directory / "orcabatch.log")
    logfile.setFormatter(formatter)

    logger.addHandler(console)
    logger.addHandler(logfile)

    return logger
