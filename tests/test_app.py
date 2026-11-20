"""Tests for the OrcaBatch application bootstrap."""

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from orcabatch import app
from orcabatch.backends.slicers import BAMBU_STUDIO, SLICERS
from orcabatch.cli.slicer_prompt import SlicerSelectionError


@dataclass
class _Result:
    """Provide the environment result shape used by the application."""

    passed: bool
    name: str = "check"
    message: str = ""


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
    monkeypatch.setattr(app, "is_configured", Mock(return_value=True))
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=BAMBU_STUDIO))
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
    assert "OrcaBatch ready. Slicer: Bambu Studio." in output


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
        slicer=BAMBU_STUDIO,
    )
    environment_service.return_value.run_checks.assert_called_once_with()


def test_slicer_is_chosen_before_environment_checks(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user is prompted with every slicer, configured ones marked, before startup proceeds."""
    _, get_config, environment_service, _ = startup_mocks
    calls: list[str] = []
    monkeypatch.setattr(
        app,
        "is_configured",
        lambda slicer, config: slicer is BAMBU_STUDIO,
    )

    def prompt(slicers: object, configured: object) -> object:
        calls.append("prompt")
        assert slicers == SLICERS
        assert configured == [BAMBU_STUDIO]
        assert not environment_service.called
        return BAMBU_STUDIO

    monkeypatch.setattr(app, "prompt_for_slicer", prompt)

    assert app.main() == 0
    assert calls == ["prompt"]


def test_no_slicer_selected_stops_startup(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If no slicer is chosen, startup stops before verification."""
    environment_service = startup_mocks[2]
    monkeypatch.setattr(
        app,
        "prompt_for_slicer",
        Mock(side_effect=SlicerSelectionError("No slicer selected.")),
    )

    assert app.main() == 1
    assert not environment_service.called
    output = capsys.readouterr().out
    assert "OrcaBatch startup failed: No slicer selected." in output
    assert "OrcaBatch ready." not in output


def test_environment_failure_lists_failed_checks(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each failed check is named so the user knows what to fix."""
    failed = Mock(passed=False, message="Bambu Studio executable not found: /x")
    failed.name = "slicer_executable"
    startup_mocks[2].return_value.run_checks.return_value = [failed]

    app.main()

    assert "slicer_executable: Bambu Studio executable not found: /x" in capsys.readouterr().out