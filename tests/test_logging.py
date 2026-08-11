from pathlib import Path

from orcabatch.core.logging import configure_logging


def test_logger_creation(tmp_path: Path):

    logger = configure_logging(tmp_path)

    assert logger is not None