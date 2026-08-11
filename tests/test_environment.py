"""Tests for the runtime environment verification service."""

from pathlib import Path

from orcabatch.core.environment import CheckResult, EnvironmentService


def test_run_checks_reports_a_successful_environment(tmp_path: Path) -> None:
    """All checks pass when every required resource is available."""
    service = _create_service(tmp_path)

    results = service.run_checks()

    assert all(result.passed for result in results)
    assert {result.name for result in results} == {
        "python",
        "configuration",
        "log_directory",
        "data_directory",
        "incoming_directory",
        "output_directory",
        "orca_executable",
        "orca_data_directory",
    }


def test_run_checks_reports_a_missing_configuration_file(tmp_path: Path) -> None:
    """A missing configuration file is reported without creating one."""
    service = _create_service(tmp_path, create_config=False)

    results = _results_by_name(service.run_checks())

    assert not results["configuration"].passed
    assert not (tmp_path / "config.yaml").exists()


def test_run_checks_reports_a_missing_orca_executable(tmp_path: Path) -> None:
    """A missing Orca executable is reported as a failed check."""
    service = _create_service(tmp_path, create_orca_executable=False)

    results = _results_by_name(service.run_checks())

    assert not results["orca_executable"].passed


def test_run_checks_reports_missing_required_directories(tmp_path: Path) -> None:
    """Incoming and output directories must already exist."""
    service = _create_service(tmp_path, create_incoming=False, create_output=False)

    results = _results_by_name(service.run_checks())

    assert not results["incoming_directory"].passed
    assert not results["output_directory"].passed


def test_run_checks_creates_log_and_data_directories(tmp_path: Path) -> None:
    """Log and data directories are created when they are absent."""
    service = _create_service(tmp_path, create_log=False, create_data=False)

    results = _results_by_name(service.run_checks())

    assert results["log_directory"].passed
    assert results["data_directory"].passed
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "data").is_dir()


def test_run_checks_reports_an_unsupported_python_version(tmp_path: Path) -> None:
    """Python versions below 3.12 are reported as unsupported."""
    service = _create_service(tmp_path, python_version=(3, 11, 9))

    results = _results_by_name(service.run_checks())

    assert not results["python"].passed
    assert "3.12" in results["python"].message


def _create_service(
    tmp_path: Path,
    *,
    create_config: bool = True,
    create_log: bool = True,
    create_data: bool = True,
    create_incoming: bool = True,
    create_output: bool = True,
    create_orca_executable: bool = True,
    python_version: tuple[int, int, int] = (3, 12, 0),
) -> EnvironmentService:
    """Create an environment service with independently controlled resources."""
    config_path = tmp_path / "config.yaml"
    log_directory = tmp_path / "logs"
    data_directory = tmp_path / "data"
    incoming_directory = tmp_path / "incoming"
    output_directory = tmp_path / "output"
    orca_executable = tmp_path / "orca"
    orca_data_directory = tmp_path / "orca-data"

    if create_config:
        config_path.touch()
    if create_log:
        log_directory.mkdir()
    if create_data:
        data_directory.mkdir()
    if create_incoming:
        incoming_directory.mkdir()
    if create_output:
        output_directory.mkdir()
    if create_orca_executable:
        orca_executable.touch()
    orca_data_directory.mkdir()

    return EnvironmentService(
        config_path=config_path,
        log_directory=log_directory,
        data_directory=data_directory,
        incoming_directory=incoming_directory,
        output_directory=output_directory,
        orca_executable=orca_executable,
        orca_data_directory=orca_data_directory,
        python_version=python_version,
    )


def _results_by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    """Return check results keyed by check name."""
    return {result.name: result for result in results}
