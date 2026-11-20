"""Execute the OrcaSlicer-family command-line interface.

This module constructs deterministic commands for OrcaSlicer and the slicers
that share its CLI (Bambu Studio, Creality Print), and runs them through one
controlled subprocess boundary. Per-slicer differences come from
:mod:`batchslicer.backends.slicers`; options a slicer lacks are refused with a
clear error rather than sent. Commands follow the OrcaSlicer CLI contract:
``orca-slicer [OPTIONS] [file.3mf/file.stl ...]``, where ``--slice`` selects a
plate and input models are positional arguments. It does not discover
installations, resolve presets, or interpret slicing profiles.

OrcaSlicer writes a ``result.json`` status file into ``--outputdir`` when one is
given, otherwise into its working directory. Commands without an output
directory therefore run from a temporary directory so the file never lands in
the caller's working directory.
"""

import logging
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from batchslicer.backends.slicers import ORCASLICER, SlicerDefinition
from batchslicer.core.config import Config, get_config
from batchslicer.core.logging import get_logger

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
    """Provide controlled access to one configured OrcaSlicer-family executable."""

    def __init__(
        self,
        *,
        slicer: SlicerDefinition = ORCASLICER,
        config: Config | None = None,
        logger: logging.Logger | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create a backend for ``slicer`` using the shared configuration and logging services."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        self._slicer = slicer
        self._config = config or get_config()
        self._logger = logger or get_logger()
        self._timeout_seconds = timeout_seconds

    @property
    def slicer(self) -> SlicerDefinition:
        """Return the slicer this backend drives."""
        return self._slicer

    def run(
        self,
        command: Sequence[str],
        *,
        working_directory: PathLike | None = None,
    ) -> OrcaResult:
        """Execute one complete command and return its captured result.

        ``working_directory`` sets where OrcaSlicer runs; ``None`` keeps the
        current directory. Commands that cannot start or exceed the timeout
        produce an unsuccessful result with exit code -1 instead of raising.
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
                cwd=working_directory,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = time.perf_counter() - started_at
            message = f"{self._slicer.display_name} timed out after {self._timeout_seconds:g} seconds."
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
            self._logger.error(
                "%s command failed to start: %s", self._slicer.display_name, message
            )
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
                "%s command completed in %.1fs: %s",
                self._slicer.display_name,
                result.elapsed,
                result.command,
            )
        else:
            self._logger.error(
                "%s command failed with exit code %s: %s\nstderr: %s",
                self._slicer.display_name,
                result.exit_code,
                result.command,
                _tail(result.stderr) or "(empty)",
            )
        return result

    def help(self) -> OrcaResult:
        """Run OrcaSlicer with its general help option."""
        return self._run_in_scratch_directory(self.build_help_command())

    def export_settings(self, output_path: PathLike) -> OrcaResult:
        """Export OrcaSlicer settings to ``output_path``."""
        return self._run_in_scratch_directory(
            self.build_export_settings_command(output_path)
        )

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
        self._require_option("--export-settings")
        return self._base_command() + (
            "--export-settings",
            str(Path(output_path).absolute()),
        )

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
        Requesting an option the selected slicer lacks raises ``ValueError``.
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
                self._require_option(option)
                command.extend((option, "1"))
        command.extend(self._slicer.slice_arguments)
        for flag, enabled in (
            ("--enable-timelapse", enable_timelapse),
            ("--no-check", no_check),
        ):
            if enabled:
                self._require_option(flag)
                command.append(flag)
        if load_settings:
            command.extend(("--load-settings", _join_file_list(load_settings)))
        if load_filaments:
            command.extend(("--load-filaments", _join_file_list(load_filaments)))
        command.append(str(Path(input_path)))
        return tuple(command)

    def _run_in_scratch_directory(self, command: Sequence[str]) -> OrcaResult:
        """Run a command without ``--outputdir`` where its result.json is discarded."""
        with tempfile.TemporaryDirectory(prefix="batchslicer-") as scratch_directory:
            return self.run(command, working_directory=scratch_directory)

    def _require_option(self, option: str) -> None:
        """Raise ``ValueError`` if the selected slicer does not accept ``option``."""
        if not self._slicer.supports(option):
            raise ValueError(f"{self._slicer.display_name} does not support {option}.")

    def _base_command(self) -> tuple[str, ...]:
        """Return the executable, its launch arguments, and the data directory.

        Paths come from the configuration service, which makes them absolute
        (relative to the configuration file) and looks bare program names up
        on PATH, so commands behave the same from any working directory.
        """
        executable = self._config.get_program(self._slicer.key)
        datadir = self._config.get_path(self._slicer.key, "datadir")
        return (
            str(executable),
            *self._slicer.launch_arguments,
            "--datadir",
            str(datadir),
        )



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
