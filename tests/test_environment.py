"""Tests for the OrcaBatch environment verification service."""

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from orcabatch.core.config import Config
from orcabatch.core.environment import CheckResult, EnvironmentService
from orcabatch.core.logging import configure_logging


@pytest.fixture(autouse=True)
def reset_orcabatch_logger() -> Generator[None, None, None]:
    """Remove service handlers so each test starts with a clean logger."""
    logger = logging.getLogger("orcabatch")
    _remove_service_handlers(logger)
    yield
    _remove_service_handlers(logger)


def test_successful_environment(tmp_path: Path) -> None:
    """All checks pass when every configured runtime path is valid."""
    config = _create_valid_config(tmp_path)
    service = _create_service(tmp_path, config=config)

    results = service.run_checks()

    assert all(result.passed for result in results)


def test_python_version_supported(tmp_path: Path) -> None:
    """Python 3.12 satisfies the runtime requirement."""
    service = _create_service(
        tmp_path,
        config=_create_valid_config(tmp_path),
        python_version=(3, 12, 0),
    )

    result = _result_by_name(service.run_checks(), "python")

    assert result.passed


def test_python_version_unsupported(tmp_path: Path) -> None:
    """Python versions below 3.12 fail without raising."""
    service = _create_service(
        tmp_path,
        config=_create_valid_config(tmp_path),
        python_version=(3, 11, 9),
    )

    result = _result_by_name(service.run_checks(), "python")

    assert not result.passed
    assert "Python 3.12+" in result.message


def test_configuration_loads(tmp_path: Path) -> None:
    """The configuration check reports success for valid YAML."""
    service = _create_service(tmp_path, config=_create_valid_config(tmp_path))

    result = _result_by_name(service.run_checks(), "configuration")

    assert result.passed


def test_missing_orca_executable(tmp_path: Path) -> None:
    """Missing Orca executable paths produce a failed check result."""
    config = _create_valid_config(tmp_path, executable=tmp_path / "missing-orca")
    service = _create_service(tmp_path, config=config)

    result = _result_by_name(service.run_checks(), "orca_executable")

    assert not result.passed
    assert "not found" in result.message


def test_orca_executable_points_to_directory(tmp_path: Path) -> None:
    """A directory is not accepted as the Orca executable."""
    executable_directory = tmp_path / "orca-directory"
    executable_directory.mkdir()
    config = _create_valid_config(tmp_path, executable=executable_directory)
    service = _create_service(tmp_path, config=config)

    result = _result_by_name(service.run_checks(), "orca_executable")

    assert not result.passed
    assert "not a file" in result.message


def test_missing_orca_data_directory(tmp_path: Path) -> None:
    """Missing Orca data directories produce a failed check result."""
    config = _create_valid_config(tmp_path, datadir=tmp_path / "missing-data")
    service = _create_service(tmp_path, config=config)

    result = _result_by_name(service.run_checks(), "orca_data_directory")

    assert not result.passed
    assert "not found" in result.message


def test_orca_datadir_points_to_file(tmp_path: Path) -> None:
    """A file is not accepted as the Orca data directory."""
    datadir_file = tmp_path / "orca-data-file"
    datadir_file.touch()
    config = _create_valid_config(tmp_path, datadir=datadir_file)
    service = _create_service(tmp_path, config=config)

    result = _result_by_name(service.run_checks(), "orca_data_directory")

    assert not result.passed
    assert "not a directory" in result.message


def test_missing_runtime_directories_are_created(tmp_path: Path) -> None:
    """Configured runtime directories are created when absent."""
    paths = _runtime_paths(tmp_path)
    config = _create_valid_config(tmp_path, runtime_paths=paths)
    service = _create_service(tmp_path, config=config)

    service.run_checks()

    assert paths["logs"].is_dir()
    assert paths["data"].is_dir()
    assert paths["incoming"].is_dir()
    assert paths["output"].is_dir()


def test_directory_creation_failure_returns_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directory creation errors become failed check results."""
    blocked_directory = tmp_path / "blocked-logs"
    paths = _runtime_paths(tmp_path)
    paths["logs"] = blocked_directory
    config = _create_valid_config(tmp_path, runtime_paths=paths)
    service = _create_service(tmp_path, config=config)
    original_mkdir = Path.mkdir

    def fail_for_blocked_directory(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Raise for the blocked test path and delegate all other directories."""
        if self == blocked_directory:
            raise OSError("permission denied")
        original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", fail_for_blocked_directory)

    result = _result_by_name(service.run_checks(), "logs_directory")

    assert not result.passed
    assert "permission denied" in result.message


def test_run_checks_returns_check_results(tmp_path: Path) -> None:
    """The public API returns a list of CheckResult objects."""
    service = _create_service(tmp_path, config=_create_valid_config(tmp_path))

    results = service.run_checks()

    assert isinstance(results, list)
    assert all(isinstance(result, CheckResult) for result in results)


def test_service_does_not_print_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Environment verification writes no stdout or stderr output."""
    service = _create_service(tmp_path, config=_create_valid_config(tmp_path))

    service.run_checks()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def _create_service(
    tmp_path: Path,
    *,
    config: Config,
    python_version: tuple[int, int, int] = (3, 12, 0),
) -> EnvironmentService:
    """Create an environment service with a test log file."""
    logger = configure_logging(log_directory=tmp_path / "service-logs")
    return EnvironmentService(
        config=config,
        logger=logger,
        python_version=python_version,
    )


def _create_valid_config(
    tmp_path: Path,
    *,
    executable: Path | None = None,
    datadir: Path | None = None,
    runtime_paths: dict[str, Path] | None = None,
) -> Config:
    """Create a Config instance backed by a temporary YAML file."""
    executable_path = executable or tmp_path / "orca"
    datadir_path = datadir or tmp_path / "orca-data"
    paths = runtime_paths or _runtime_paths(tmp_path)

    if executable is None:
        executable_path.touch()
    if datadir is None:
        datadir_path.mkdir()

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            (
                "orca:",
                f'  executable: "{executable_path}"',
                f'  datadir: "{datadir_path}"',
                "paths:",
                f'  incoming: "{paths["incoming"]}"',
                f'  output: "{paths["output"]}"',
                f'  logs: "{paths["logs"]}"',
                f'  data: "{paths["data"]}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return Config(config_path)


def _runtime_paths(tmp_path: Path) -> dict[str, Path]:
    """Return temporary runtime paths used by environment tests."""
    return {
        "incoming": tmp_path / "incoming",
        "output": tmp_path / "output",
        "logs": tmp_path / "logs",
        "data": tmp_path / "data",
    }


def _result_by_name(results: list[CheckResult], name: str) -> CheckResult:
    """Return one check result by name."""
    for result in results:
        if result.name == name:
            return result
    raise AssertionError(f"Missing check result: {name}")


def _remove_service_handlers(logger: logging.Logger) -> None:
    """Detach and close file handlers created by the logging service."""
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler) and handler.get_name() == "orcabatch-file":
            logger.removeHandler(handler)
            handler.close()
