"""Execute the OrcaSlicer command-line interface.

This module constructs deterministic OrcaSlicer commands and runs them through
one controlled subprocess boundary. It does not discover installations,
resolve presets, or interpret slicing profiles.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
import time
from typing import TypeAlias

from orcabatch.core.config import Config, get_config
from orcabatch.core.logging import get_logger


PathLike: TypeAlias = str | Path


@dataclass(frozen=True, slots=True)
class OrcaResult:
    """Capture the result of one OrcaSlicer command execution."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    elapsed: float
    command: tuple[str, ...]


class OrcaBackend:
    """Provide controlled access to the configured OrcaSlicer executable."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a backend using the shared configuration and logging services."""
        self._config = config or get_config()
        self._logger = logger or get_logger()

    def run(self, command: Sequence[str]) -> OrcaResult:
        """Execute one complete command and return its captured result."""
        executed_command = tuple(str(argument) for argument in command)
        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                executed_command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            elapsed = time.perf_counter() - started_at
            message = str(error)
            self._logger.error("OrcaSlicer command failed to start: %s", message)
            return OrcaResult(False, -1, "", message, elapsed, executed_command)

        elapsed = time.perf_counter() - started_at
        result = OrcaResult(
            completed.returncode == 0,
            completed.returncode,
            completed.stdout,
            completed.stderr,
            elapsed,
            executed_command,
        )
        self._logger.info(
            "OrcaSlicer command completed with exit code %s: %s",
            result.exit_code,
            result.command,
        )
        return result

    def help(self) -> OrcaResult:
        """Run OrcaSlicer with its general help option."""
        return self.run(self.build_help_command())

    def version(self) -> OrcaResult:
        """Run OrcaSlicer with its version option."""
        return self.run(self.build_version_command())

    def export_settings(self, output_path: PathLike) -> OrcaResult:
        """Export OrcaSlicer settings to ``output_path``."""
        return self.run(self.build_export_settings_command(output_path))

    def slice(
        self,
        input_path: PathLike,
        output_directory: PathLike,
        *,
        orient: bool = False,
        arrange: bool = False,
        enable_timelapse: bool = False,
        skip_modified_gcodes: bool = False,
        no_check: bool = False,
        load_settings: Sequence[PathLike] = (),
        load_filaments: Sequence[PathLike] = (),
    ) -> OrcaResult:
        """Slice one STL input into ``output_directory`` with requested options."""
        return self.run(
            self.build_slice_command(
                input_path,
                output_directory,
                orient=orient,
                arrange=arrange,
                enable_timelapse=enable_timelapse,
                skip_modified_gcodes=skip_modified_gcodes,
                no_check=no_check,
                load_settings=load_settings,
                load_filaments=load_filaments,
            )
        )

    def build_help_command(self) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`help`."""
        return self._base_command() + ("--help",)

    def build_version_command(self) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`version`."""
        return self._base_command() + ("--version",)

    def build_export_settings_command(self, output_path: PathLike) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`export_settings`."""
        return self._base_command() + ("--export-settings", str(Path(output_path)))

    def build_slice_command(
        self,
        input_path: PathLike,
        output_directory: PathLike,
        *,
        orient: bool = False,
        arrange: bool = False,
        enable_timelapse: bool = False,
        skip_modified_gcodes: bool = False,
        no_check: bool = False,
        load_settings: Sequence[PathLike] = (),
        load_filaments: Sequence[PathLike] = (),
    ) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`slice`."""
        command = list(
            self._base_command()
            + (
                "--slice",
                str(Path(input_path)),
                "--outputdir",
                str(Path(output_directory)),
            )
        )
        for flag, enabled in (
            ("--orient", orient),
            ("--arrange", arrange),
            ("--enable-timelapse", enable_timelapse),
            ("--skip-modified-gcodes", skip_modified_gcodes),
            ("--no-check", no_check),
        ):
            if enabled:
                command.append(flag)
        for settings_path in load_settings:
            command.extend(("--load-settings", str(Path(settings_path))))
        for filament_path in load_filaments:
            command.extend(("--load-filaments", str(Path(filament_path))))
        return tuple(command)

    def _base_command(self) -> tuple[str, ...]:
        """Return the executable and configured OrcaSlicer data directory."""
        executable = self._configured_path("executable")
        datadir = self._configured_path("datadir")
        return (str(executable), "--datadir", str(datadir))

    def _configured_path(self, key: str) -> Path:
        """Return one required configured Orca path."""
        value = self._config.get("orca", key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Configuration value orca.{key} must not be empty.")
        return Path(value)