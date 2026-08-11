"""Verify the OrcaBatch runtime environment without starting the application.

This module checks required files, directories, and the Python version. It does
not create configuration files, launch Orca, validate application data, or
terminate the application.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import sys


@dataclass(frozen=True)
class CheckResult:
    """Describe the outcome of one environment verification check."""

    name: str
    passed: bool
    message: str


class EnvironmentService:
    """Verify required runtime files, directories, and Python version."""

    def __init__(
        self,
        *,
        config_path: Path,
        log_directory: Path,
        data_directory: Path,
        incoming_directory: Path,
        output_directory: Path,
        orca_executable: Path,
        orca_data_directory: Path,
        python_version: tuple[int, int, int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Store the paths and runtime dependencies needed for verification."""
        self._config_path = config_path
        self._log_directory = log_directory
        self._data_directory = data_directory
        self._incoming_directory = incoming_directory
        self._output_directory = output_directory
        self._orca_executable = orca_executable
        self._orca_data_directory = orca_data_directory
        self._python_version = python_version or sys.version_info[:3]
        self._logger = logger or logging.getLogger(__name__)

    def run_checks(self) -> list[CheckResult]:
        """Run every environment verification and return their outcomes."""
        results = [
            self._check_python(),
            self._check_configuration(),
            *self._check_directories(),
            *self._check_orca(),
        ]

        for result in results:
            self._logger.info(
                "Environment check %s: %s (%s)",
                result.name,
                "passed" if result.passed else "failed",
                result.message,
            )

        return results

    def _check_python(self) -> CheckResult:
        """Verify that the active Python version is supported."""
        supported = self._python_version >= (3, 12, 0)
        version = ".".join(str(part) for part in self._python_version)
        message = (
            f"Python {version} is supported."
            if supported
            else f"Python {version} is unsupported; Python 3.12 or newer is required."
        )
        return CheckResult("python", supported, message)

    def _check_configuration(self) -> CheckResult:
        """Verify that the configured file already exists."""
        exists = self._config_path.is_file()
        message = (
            f"Configuration file exists: {self._config_path}."
            if exists
            else f"Configuration file is missing: {self._config_path}."
        )
        return CheckResult("configuration", exists, message)

    def _check_directories(self) -> list[CheckResult]:
        """Verify required directories and create only writable runtime directories."""
        return [
            self._check_creatable_directory("log_directory", self._log_directory),
            self._check_creatable_directory("data_directory", self._data_directory),
            self._check_existing_directory("incoming_directory", self._incoming_directory),
            self._check_existing_directory("output_directory", self._output_directory),
        ]

    def _check_orca(self) -> list[CheckResult]:
        """Verify the Orca executable and its data directory."""
        executable_exists = self._orca_executable.is_file()
        executable_message = (
            f"Orca executable exists: {self._orca_executable}."
            if executable_exists
            else f"Orca executable is missing: {self._orca_executable}."
        )
        return [
            CheckResult("orca_executable", executable_exists, executable_message),
            self._check_existing_directory("orca_data_directory", self._orca_data_directory),
        ]

    def _check_creatable_directory(self, name: str, directory: Path) -> CheckResult:
        """Verify a directory exists or create it when possible."""
        if directory.is_dir():
            return CheckResult(name, True, f"Directory exists: {directory}.")
        if directory.exists():
            return CheckResult(name, False, f"Path is not a directory: {directory}.")

        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return CheckResult(name, False, f"Cannot create directory {directory}: {error}.")

        return CheckResult(name, True, f"Directory created: {directory}.")

    def _check_existing_directory(self, name: str, directory: Path) -> CheckResult:
        """Verify that a required directory already exists."""
        exists = directory.is_dir()
        message = (
            f"Directory exists: {directory}."
            if exists
            else f"Required directory is missing: {directory}."
        )
        return CheckResult(name, exists, message)
