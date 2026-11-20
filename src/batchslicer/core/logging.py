"""Configure and provide the shared BatchSlicer application logger.

This module owns the application's file logger. It does not configure console
output, rotate logs, parse configuration files, or format structured logs.
"""

import logging
from pathlib import Path

from batchslicer.core.locations import default_paths


_LOGGER_NAME = "batchslicer"
_FILE_HANDLER_NAME = "batchslicer-file"
_LOG_FILE_NAME = "batchslicer.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(
    *,
    log_directory: Path | None = None,
    level: int | str = logging.INFO,
) -> logging.Logger:
    """Configure and return the shared BatchSlicer file logger.

    ``log_directory`` defaults to the standard per-user log folder.
    Repeated calls retain one BatchSlicer file handler and update its log level.
    """
    if log_directory is None:
        log_directory = default_paths()["logs"]
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file = log_directory / _LOG_FILE_NAME
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    handler = _get_file_handler(logger)
    if handler is not None and Path(handler.baseFilename) != log_file.resolve():
        logger.removeHandler(handler)
        handler.close()
        handler = None

    if handler is None:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.set_name(_FILE_HANDLER_NAME)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)

    handler.setLevel(level)
    return logger


def get_logger() -> logging.Logger:
    """Return the configured BatchSlicer application logger."""
    logger = logging.getLogger(_LOGGER_NAME)
    if _get_file_handler(logger) is None:
        return configure_logging()
    return logger


def _get_file_handler(logger: logging.Logger) -> logging.FileHandler | None:
    """Return the file handler owned by this service, if configured."""
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.get_name() == _FILE_HANDLER_NAME:
            return handler
    return None
