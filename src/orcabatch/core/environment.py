"""Verify that the OrcaBatch runtime environment is ready.

This module checks Python, configuration, runtime directories, and configured
OrcaSlicer paths before application startup continues. It returns structured
results and writes summary messages through the OrcaBatch logging service. It
does not print output, launch external processes, validate databases, validate
presets, or create configuration files.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import sys
from typing import Any

from orcabatch.core.config import Config, get_config
from orcabatch.core.logging import get_logger


_PYTHON_MINIMUM = (3, 12)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Represent the outcome of one environment verification check."""

    name: str
    passed: bool
    message: str


class EnvironmentService:
    """Verify runtime prerequisites needed for OrcaBatch startup."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        logger: logging.Logger | None = None,
        python_version: tuple[int, int, int] | None = None,
    ) -> None:
        """Create an environment service with injectable collaborators."""
        self._config = config
        self._logger = logger or get_logger()
        self._python_version = python_version or sys.version_info[:3]

    def run_checks(self) -> list[CheckResult]:
        """Run all environment checks and return their structured results."""
        self._logger.info("Starting environment verification.")
        results = [
            self._check_python(),
            self._check_configuration(),
            self._check_logs_directory(),
            self._check_data_directory(),
            self._check_incoming_directory(),
            self._check_output_directory(),
            self._check_orca_executable(),
            self._check_orca_data_directory(),
        ]

        failed_results = [result for result in results if not result.passed]
        for result in failed_results:
            self._logger.warning(
                "Environment check failed: %s - %s",
                result.name,
                result.message,
            )

        if not failed_results:
            self._logger.info("Environment verification completed successfully.")

        return results

    def _check_python(self) -> CheckResult:
        """Verify that the active Python version meets the minimum version."""
        if self._python_version >= _PYTHON_MINIMUM:
            return CheckResult(
                name="python",
                passed=True,
                message="Python version is supported.",
            )

        minimum = ".".join(str(part) for part in _PYTHON_MINIMUM)
        current = ".".join(str(part) for part in self._python_version[:2])
        return CheckResult(
            name="python",
            passed=False,
            message=f"Python {minimum}+ is required; found Python {current}.",
        )

    def _check_configuration(self) -> CheckResult:
        """Verify that application configuration can be loaded."""
        try:
            self._get_config_service().load()
        except (FileNotFoundError, ValueError) as error:
            return CheckResult(
                name="configuration",
                passed=False,
                message=str(error),
            )

        return CheckResult(
            name="configuration",
            passed=True,
            message="Configuration loaded successfully.",
        )

    def _check_logs_directory(self) -> CheckResult:
        """Verify that the configured logs directory exists or can be created."""
        return self._check_runtime_directory("logs_directory", "logs")

    def _check_data_directory(self) -> CheckResult:
        """Verify that the configured data directory exists or can be created."""
        return self._check_runtime_directory("data_directory", "data")

    def _check_incoming_directory(self) -> CheckResult:
        """Verify that the configured incoming directory exists or can be created."""
        return self._check_runtime_directory("incoming_directory", "incoming")

    def _check_output_directory(self) -> CheckResult:
        """Verify that the configured output directory exists or can be created."""
        return self._check_runtime_directory("output_directory", "output")

    def _check_orca_executable(self) -> CheckResult:
        """Verify that the configured Orca executable exists and is a file."""
        name = "orca_executable"
        try:
            executable = self._get_configured_path("orca", "executable")
        except (FileNotFoundError, ValueError, KeyError) as error:
            return CheckResult(name=name, passed=False, message=str(error))

        if not executable.exists():
            return CheckResult(
                name=name,
                passed=False,
                message=f"Orca executable not found: {executable}",
            )

        if not executable.is_file():
            return CheckResult(
                name=name,
                passed=False,
                message=f"Orca executable is not a file: {executable}",
            )

        return CheckResult(
            name=name,
            passed=True,
            message="Orca executable exists.",
        )

    def _check_orca_data_directory(self) -> CheckResult:
        """Verify that the configured Orca data directory exists and is a directory."""
        name = "orca_data_directory"
        try:
            data_directory = self._get_configured_path("orca", "datadir")
        except (FileNotFoundError, ValueError, KeyError) as error:
            return CheckResult(name=name, passed=False, message=str(error))

        if not data_directory.exists():
            return CheckResult(
                name=name,
                passed=False,
                message=f"Orca data directory not found: {data_directory}",
            )

        if not data_directory.is_dir():
            return CheckResult(
                name=name,
                passed=False,
                message=f"Orca data directory is not a directory: {data_directory}",
            )

        return CheckResult(
            name=name,
            passed=True,
            message="Orca data directory exists.",
        )

    def _check_runtime_directory(self, name: str, key: str) -> CheckResult:
        """Verify that one configured runtime directory exists or can be created."""
        try:
            directory = self._get_configured_path("paths", key)
            directory.mkdir(parents=True, exist_ok=True)
        except (FileNotFoundError, ValueError, KeyError, OSError) as error:
            return CheckResult(name=name, passed=False, message=str(error))

        if not directory.is_dir():
            return CheckResult(
                name=name,
                passed=False,
                message=f"Configured path is not a directory: {directory}",
            )

        return CheckResult(
            name=name,
            passed=True,
            message=f"Runtime directory is available: {directory}",
        )

    def _get_configured_path(self, section: str, key: str) -> Path:
        """Return a non-empty configured path value."""
        value: Any = self._get_config_service().get(section, key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Configuration value {section}.{key} must not be empty.")
        return Path(value)

    def _get_config_service(self) -> Config:
        """Return the injected or shared configuration service."""
        if self._config is None:
            self._config = get_config()
        return self._config
