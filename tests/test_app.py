"""Tests for the OrcaBatch application bootstrap."""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from orcabatch import app


@dataclass
class _Result:
    """Provide the environment result shape used by the application."""

    passed: bool


@pytest.fixture
def startup_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock, Mock, Mock]:
    """Replace startup services with test doubles."""
    logger = Mock()
    configure_logging = Mock(return_value=logger)
    get_config = Mock(return_value=Mock())
    environment_service = Mock()
    environment_service.return_value.run_checks.return_value = [_Result(passed=True)]

    monkeypatch.setattr(app, "configure_logging", configure_logging)
    monkeypatch.setattr(app, "get_config", get_config)
    monkeypatch.setattr(app, "EnvironmentService", environment_service)
    return configure_logging, get_config, environment_service, logger


def test_successful_startup_returns_zero_and_reports_ready(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Successful startup displays the banner and readiness message."""
    result = app.main()

    assert result == 0
    output = capsys.readouterr().out
    assert app.get_banner() in output
    assert "OrcaBatch ready." in output


def test_environment_failure_returns_nonzero_without_ready_message(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failed environment checks prevent the application from becoming ready."""
    startup_mocks[2].return_value.run_checks.return_value = [_Result(passed=False)]

    result = app.main()

    assert result != 0
    assert "OrcaBatch ready." not in capsys.readouterr().out


def test_configuration_failure_is_handled_cleanly(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expected configuration failures return a status without a traceback."""
    startup_mocks[1].side_effect = FileNotFoundError("missing config")

    result = app.main()

    assert result != 0
    assert "OrcaBatch startup failed: missing config" in capsys.readouterr().out


def test_startup_uses_services_in_order(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Startup delegates configuration and environment work to existing services."""
    configure_logging, get_config, environment_service, logger = startup_mocks

    app.main()

    configure_logging.assert_called_once_with()
    get_config.assert_called_once_with()
    environment_service.assert_called_once_with(
        config=get_config.return_value,
        logger=logger,
    )
    environment_service.return_value.run_checks.assert_called_once_with()