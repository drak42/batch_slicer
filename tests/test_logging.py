"""Tests for the shared BatchSlicer logging service."""

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from batchslicer.core.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_batchslicer_logger() -> Generator[None, None, None]:
    """Remove service handlers so each test starts with a clean logger."""
    logger = logging.getLogger("batchslicer")
    _remove_service_handlers(logger)
    yield
    _remove_service_handlers(logger)


def test_configure_logging_creates_the_default_log_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """By default the log goes to the standard per-user state folder."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    configure_logging()

    assert (tmp_path / "state" / "batchslicer" / "batchslicer.log").is_file()


def test_configure_logging_supports_a_custom_level(tmp_path: Path) -> None:
    """The logger and file handler use the requested log level."""
    logger = configure_logging(log_directory=tmp_path / "logs", level=logging.DEBUG)

    assert logger.level == logging.DEBUG
    assert all(handler.level == logging.DEBUG for handler in _service_handlers(logger))


def test_configure_logging_writes_to_the_log_file(tmp_path: Path) -> None:
    """Messages written through the logger are persisted to its file."""
    log_directory = tmp_path / "logs"
    logger = configure_logging(log_directory=log_directory)

    logger.info("Logging service configured.")
    _flush_handlers(logger)

    assert "Logging service configured." in (log_directory / "batchslicer.log").read_text()


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    """Repeated configuration returns one logger with one file handler."""
    first_logger = configure_logging(log_directory=tmp_path / "logs")
    second_logger = configure_logging(log_directory=tmp_path / "logs")

    assert first_logger is second_logger
    assert len(_service_handlers(second_logger)) == 1


def test_get_logger_returns_the_configured_logger(tmp_path: Path) -> None:
    """Consumers retrieve the logger configured by the service."""
    configured_logger = configure_logging(log_directory=tmp_path / "logs")

    assert get_logger() is configured_logger


def _flush_handlers(logger: logging.Logger) -> None:
    """Flush logger handlers so tests can inspect file output."""
    for handler in logger.handlers:
        handler.flush()


def _remove_service_handlers(logger: logging.Logger) -> None:
    """Detach and close file handlers created by the logging service."""
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler) and handler.get_name() == "batchslicer-file":
            logger.removeHandler(handler)
            handler.close()


def _service_handlers(logger: logging.Logger) -> list[logging.FileHandler]:
    """Return the file handlers created by the logging service."""
    return [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler) and handler.get_name() == "batchslicer-file"
    ]


def test_log_file_is_rotated_when_it_grows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The log never grows without limit: old content moves to numbered files."""
    from batchslicer.core import logging as logging_service

    monkeypatch.setattr(logging_service, "MAX_LOG_BYTES", 2_000)
    logger = configure_logging(log_directory=tmp_path / "logs")

    for number in range(200):
        logger.info("line %d %s", number, "x" * 50)

    log_files = sorted(path.name for path in (tmp_path / "logs").iterdir())
    assert log_files == ["batchslicer.log", "batchslicer.log.1", "batchslicer.log.2", "batchslicer.log.3"]
    assert (tmp_path / "logs" / "batchslicer.log").stat().st_size <= 2_000
