"""Execute the OrcaSlicer command-line interface.

This module constructs deterministic OrcaSlicer commands and runs them through
one controlled subprocess boundary. Commands follow the OrcaSlicer CLI contract:
``orca-slicer [OPTIONS] [file.3mf/file.stl ...]``, where ``--slice`` selects a
plate and input models are positional arguments. It does not discover
installations, resolve presets, or interpret slicing profiles.
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

ALL_PLATES = 0
"""Plate number that tells OrcaSlicer to slice every plate."""

DEFAULT_TIMEOUT_SECONDS = 1800.0
"""Maximum time one OrcaSlicer command may run before it is stopped."""

_FILE_LIST_SEPARATOR = ";"
_MAX_LOGGED_STDERR_CHARACTERS = 2000


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
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create a backend using the shared configuration and logging services."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        self._config = config or get_config()
        self._logger = logger or get_logger()
        self._timeout_seconds = timeout_seconds

    def run(self, command: Sequence[str]) -> OrcaResult:
        """Execute one complete command and return its captured result.

        Commands that cannot start or exceed the timeout produce an
        unsuccessful result with exit code -1 instead of raising.
        """
        executed_command = tuple(str(argument) for argument in command)
        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                executed_command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = time.perf_counter() - started_at
            message = f"OrcaSlicer timed out after {self._timeout_seconds:g} seconds."
            self._logger.error("%s Command: %s", message, executed_command)
            stderr = _as_text(error.stderr)
            return OrcaResult(
                False,
                -1,
                _as_text(error.stdout),
                f"{stderr}\n{message}" if stderr else message,
                elapsed,
                executed_command,
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
        if result.success:
            self._logger.info(
                "OrcaSlicer command completed in %.1fs: %s",
                result.elapsed,
                result.command,
            )
        else:
            self._logger.error(
                "OrcaSlicer command failed with exit code %s: %s\nstderr: %s",
                result.exit_code,
                result.command,
                _tail(result.stderr) or "(empty)",
            )
        return result

    def help(self) -> OrcaResult:
        """Run OrcaSlicer with its general help option."""
        return self.run(self.build_help_command())

    def export_settings(self, output_path: PathLike) -> OrcaResult:
        """Export OrcaSlicer settings to ``output_path``."""
        return self.run(self.build_export_settings_command(output_path))

    def slice(
        self,
        input_path: PathLike,
        output_directory: PathLike,
        *,
        plate: int = ALL_PLATES,
        orient: bool = False,
        arrange: bool = False,
        enable_timelapse: bool = False,
        skip_modified_gcodes: bool = False,
        no_check: bool = False,
        load_settings: Sequence[PathLike] = (),
        load_filaments: Sequence[PathLike] = (),
    ) -> OrcaResult:
        """Slice one model file into ``output_directory`` with requested options."""
        return self.run(
            self.build_slice_command(
                input_path,
                output_directory,
                plate=plate,
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

    def build_export_settings_command(self, output_path: PathLike) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`export_settings`."""
        return self._base_command() + ("--export-settings", str(Path(output_path)))

    def build_slice_command(
        self,
        input_path: PathLike,
        output_directory: PathLike,
        *,
        plate: int = ALL_PLATES,
        orient: bool = False,
        arrange: bool = False,
        enable_timelapse: bool = False,
        skip_modified_gcodes: bool = False,
        no_check: bool = False,
        load_settings: Sequence[PathLike] = (),
        load_filaments: Sequence[PathLike] = (),
    ) -> tuple[str, ...]:
        """Return the deterministic command used by :meth:`slice`.

        ``plate`` is 0 for all plates or the 1-based plate number. Options that
        OrcaSlicer expects a value for (``--orient``, ``--arrange``,
        ``--skip-modified-gcodes``) are passed ``1`` when enabled. Settings and
        filament files are joined into the single semicolon-separated argument
        OrcaSlicer expects. The input model is the final positional argument.
        """
        if plate < 0:
            raise ValueError(f"Plate must be 0 (all plates) or a plate number: {plate}")

        command = list(
            self._base_command()
            + (
                "--slice",
                str(plate),
                "--outputdir",
                str(Path(output_directory)),
            )
        )
        for option, enabled in (
            ("--orient", orient),
            ("--arrange", arrange),
            ("--skip-modified-gcodes", skip_modified_gcodes),
        ):
            if enabled:
                command.extend((option, "1"))
        for flag, enabled in (
            ("--enable-timelapse", enable_timelapse),
            ("--no-check", no_check),
        ):
            if enabled:
                command.append(flag)
        if load_settings:
            command.extend(("--load-settings", _join_file_list(load_settings)))
        if load_filaments:
            command.extend(("--load-filaments", _join_file_list(load_filaments)))
        command.append(str(Path(input_path)))
        return tuple(command)

    def _base_command(self) -> tuple[str, ...]:
        """Return the executable and configured OrcaSlicer data directory."""
        executable = self._configured_path("executable")
        datadir = self._configured_path("datadir")
        return (str(executable), "--datadir", str(datadir))

    def _configured_path(self, key: str) -> Path:
        """Return one required configured Orca path."""
        value = self._config.get("orca", key)
        if isinstance(value, str):
            if not value:
                raise ValueError(f"Configuration value orca.{key} must not be empty.")
            return Path(value)
        if isinstance(value, Path):
            return value
        raise ValueError(f"Configuration value orca.{key} must be a path.")


def _join_file_list(paths: Sequence[PathLike]) -> str:
    """Join paths into OrcaSlicer's semicolon-separated file list argument."""
    values = [str(Path(path)) for path in paths]
    for value in values:
        if _FILE_LIST_SEPARATOR in value:
            raise ValueError(
                f"OrcaSlicer file lists cannot contain paths with '{_FILE_LIST_SEPARATOR}': {value}"
            )
    return _FILE_LIST_SEPARATOR.join(values)


def _as_text(value: str | bytes | None) -> str:
    """Return captured process output as text.

    ``TimeoutExpired`` can carry bytes even when the process ran in text mode.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _tail(text: str) -> str:
    """Return the end of ``text``, which is where OrcaSlicer reports errors."""
    text = text.strip()
    if len(text) <= _MAX_LOGGED_STDERR_CHARACTERS:
        return text
    return "..." + text[-_MAX_LOGGED_STDERR_CHARACTERS:]
