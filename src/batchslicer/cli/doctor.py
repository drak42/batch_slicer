"""Run ``batchslicer doctor``: check the installation and report what was found.

Shows the BatchSlicer and Python versions, which configuration file is used,
where BatchSlicer keeps its files, and for each configured slicer whether its
program runs and accepts BatchSlicer's commands, whether its settings folder
exists, and how many printers it offers, then whether each networked printer
(the ``printers`` section, for --send) answers. Problems are listed with what to do
about them. The report is meant for both fixing a setup and reporting bugs.
This module only checks and reports; it does not change anything except that
OrcaSlicer's built-in presets may be extracted into the cache, as for a run.
"""

import logging
import os
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from batchslicer.backends.orca import OrcaBackend
from batchslicer.backends.presets import PresetError, PresetLibrary
from batchslicer.backends.profiles import find_system_profiles
from batchslicer.backends.slicers import SLICERS, SlicerDefinition, is_configured
from batchslicer.core.config import Config, find_config_file
from batchslicer.core.locations import CONFIG_ENVIRONMENT_VARIABLE, default_paths
from batchslicer.domain.printers import PrinterHostError, printer_hosts
from batchslicer.infrastructure.printer_api import PrinterError
from batchslicer.infrastructure.printer_clients import client_for
from batchslicer.infrastructure.profiles import ProfileError, ProfileStore
from batchslicer.version import get_version_string

_HELP_TIMEOUT_SECONDS = 120.0
_FOLDER_KEYS = ("incoming", "output", "logs", "data", "profiles")


@dataclass(frozen=True, slots=True)
class DoctorOptions:
    """Options for ``batchslicer doctor``."""

    config: Path | None = None


@dataclass
class _Report:
    """Collects the report's lines and problems."""

    write: Callable[[str], None]
    problems: list[str] = field(default_factory=list)

    def line(self, text: str = "") -> None:
        """Write one line of the report."""
        self.write(text)

    def problem(self, text: str) -> None:
        """Record and show a problem."""
        self.problems.append(text)
        self.write(f"  PROBLEM: {text}")


def run_doctor(
    options: DoctorOptions,
    *,
    write: Callable[[str], None] = print,
) -> int:
    """Check the installation, write the report, and return the number of problems."""
    report = _Report(write)
    report.line(f"{get_version_string()} (Python {platform.python_version()}, {platform.platform()})")
    report.line("")

    config = _check_configuration(options, report)
    _check_folders(config, report)
    if config is not None:
        _check_slicers(config, report)
        _check_printers(config, report)
        _check_profiles(config, report)

    if report.problems:
        count = len(report.problems)
        report.line(f"{count} problem{'s' if count != 1 else ''} found:")
        for text in report.problems:
            report.line(f"  - {text}")
    else:
        report.line("No problems found.")
    return len(report.problems)


def _check_configuration(options: DoctorOptions, report: _Report) -> Config | None:
    """Find and load the configuration, reporting how it was found."""
    report.line("Configuration:")
    try:
        path = find_config_file(options.config)
    except FileNotFoundError as error:
        report.problem(str(error))
        report.line("")
        return None

    if options.config is not None:
        source = "--config"
    elif os.environ.get(CONFIG_ENVIRONMENT_VARIABLE):
        source = CONFIG_ENVIRONMENT_VARIABLE
    elif not path.is_absolute():
        source = "the current folder"
    else:
        source = "the standard location"
    report.line(f"  {path.absolute()} (from {source})")
    config = Config(path)
    try:
        config.load()
    except (FileNotFoundError, ValueError) as error:
        report.problem(str(error))
        report.line("")
        return None
    report.line("")
    return config


def _check_folders(config: Config | None, report: _Report) -> None:
    """Show where BatchSlicer keeps its files."""
    report.line("Folders:")
    defaults = default_paths()
    for key in _FOLDER_KEYS:
        try:
            path = config.get_path("paths", key) if config is not None else defaults[key]
        except (KeyError, ValueError) as error:
            report.problem(f"paths.{key}: {error}")
            continue
        state = "exists" if path.exists() else "not created yet"
        report.line(f"  {key:<9} {path}  ({state})")
        if path.exists() and key != "profiles" and not path.is_dir():
            report.problem(f"paths.{key} is not a folder: {path}")
    report.line("")


def _check_slicers(config: Config, report: _Report) -> None:
    """Check every configured slicer."""
    report.line("Slicers:")
    quiet = logging.getLogger("batchslicer.doctor")
    quiet.propagate = False
    if not quiet.handlers:
        quiet.addHandler(logging.NullHandler())

    configured = [slicer for slicer in SLICERS if is_configured(slicer, config)]
    for slicer in SLICERS:
        if slicer not in configured:
            report.line(f"  {slicer.display_name}: not configured")
            continue
        _check_slicer(slicer, config, quiet, report)
    if not configured:
        report.problem("No slicer is configured. Run 'batchslicer setup'.")
    report.line("")


def _check_slicer(
    slicer: SlicerDefinition,
    config: Config,
    logger: logging.Logger,
    report: _Report,
) -> None:
    """Check one slicer's program, settings folder and presets."""
    report.line(f"  {slicer.display_name}:")
    try:
        executable = config.get_program(slicer.key)
        data_directory = config.get_path(slicer.key, "datadir")
    except (KeyError, ValueError) as error:
        report.problem(f"{slicer.display_name}: {error}")
        return

    report.line(f"    program:  {executable}")
    report.line(f"    settings: {data_directory}")
    if not executable.is_file():
        report.problem(f"{slicer.display_name} program not found: {executable}")
        return
    if not data_directory.is_dir():
        report.problem(
            f"{slicer.display_name} settings folder not found: {data_directory}. "
            "Open the slicer once, or run 'batchslicer setup' again."
        )
        return

    backend = OrcaBackend(
        slicer=slicer, config=config, logger=logger, timeout_seconds=_HELP_TIMEOUT_SECONDS
    )
    result = backend.help()
    help_text = result.stdout + result.stderr
    if result.success and "--slice" in help_text:
        report.line(f"    runs:     yes ({result.elapsed:.1f}s)")
    else:
        detail = (result.stderr.strip().splitlines() or ["no output"])[-1]
        report.problem(
            f"{slicer.display_name} did not run its command-line help "
            f"(exit code {result.exit_code}): {detail}"
        )
        return

    if not slicer.supports_preset_selection:
        report.line("    presets:  selection not available yet for this slicer")
        return
    try:
        system_directory = find_system_profiles(
            executable,
            data_directory,
            config.get_path("paths", "data") / "slicer-profiles",
            logger=logger,
        )
        library = PresetLibrary(
            data_directory,
            str(slicer.app_config_name),
            system_directory=system_directory,
            logger=logger,
        )
        printers = library.printers()
    except (PresetError, OSError) as error:
        report.problem(
            f"{slicer.display_name} presets could not be read: {error} "
            f"(Has {slicer.display_name} been opened and set up with your printers?)"
        )
        return
    if not printers:
        report.problem(
            f"{slicer.display_name} offers no printers. Add your printers in "
            f"{slicer.display_name}, close it, and check again."
        )
        return
    mine = sum(1 for printer in printers if printer.is_user)
    report.line(
        f"    presets:  {len(printers)} printer{'s' if len(printers) != 1 else ''}"
        + (f" ({mine} of your own)" if mine else "")
    )


def _check_printers(config: Config, report: _Report) -> None:
    """Check that every printer G-code can be sent to answers, and show what is loaded in its CFS."""
    report.line("Printers (for --send):")
    try:
        hosts = printer_hosts(config.section("printers"))
    except PrinterHostError as error:
        report.problem(str(error))
        report.line("")
        return
    if not hosts:
        report.line("  none configured")
    for host in hosts.values():
        client = client_for(host, timeout_seconds=5.0)
        try:
            status = client.status()
        except PrinterError as error:
            report.line(f"  {host.describe()}")
            report.problem(f"{error} (Is the printer on and on this network?)")
            continue
        report.line(
            f"  {host.describe()}: answers, {status.state}"
            + (f", {status.software}" if status.software else "")
        )
        try:
            loaded = client.loaded_filaments()
        except PrinterError as error:
            report.line(f"    loaded filaments: could not be read ({error})")
            continue
        if loaded:
            report.line("    loaded filaments (for --loaded-filaments):")
            for filament in loaded:
                report.line(f"      {filament.describe()}  ({filament.colour})")
    report.line("")


def _check_profiles(config: Config, report: _Report) -> None:
    """Check that saved profiles can be read."""
    report.line("Profiles:")
    try:
        store = ProfileStore(config.get_path("paths", "profiles"))
        saved = store.load()
    except (ProfileError, KeyError, ValueError) as error:
        report.problem(str(error))
        report.line("")
        return
    names = ", ".join(sorted(saved)) if saved else "none saved yet"
    report.line(f"  {len(saved)} saved ({names})")
    report.line("")
