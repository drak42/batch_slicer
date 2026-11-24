"""Coordinate the BatchSlicer application lifecycle.

Startup configures logging, loads configuration, selects the slicer, verifies
the environment for it, and selects the printer, filament and process presets
where the slicer supports it. The models to slice (one file, or a folder and
its subfolders) and the output folder are then selected, and the models are
sliced into job folders. With --send the G-code is then uploaded to a
networked printer (checked before slicing starts), and with --start printed. Each choice comes from the command line when given
there, and is otherwise asked for (unless ``--no-prompt`` is used).

Errors are reported on stderr. Ctrl+C stops cleanly with exit status 130 (a
batch keeps the models already sliced), and an unexpected error is reported in
one line with the full details written to the log. Exit statuses: 0 success,
1 failure, 2 invalid option (from argparse), 130 interrupted.
"""

import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from batchslicer.backends.orca import OrcaBackend
from batchslicer.backends.presets import PresetError, PresetLibrary
from batchslicer.backends.profiles import find_system_profiles
from batchslicer.backends.projects import is_project, project_filaments
from batchslicer.backends.slicers import SLICERS, SlicerDefinition, get_slicer, is_configured
from batchslicer.banner import get_banner
from batchslicer.cli.arguments import RunOptions, parse_arguments
from batchslicer.cli.doctor import DoctorOptions, run_doctor
from batchslicer.cli.file_prompt import (
    SliceInput,
    exclude_models,
    input_from_path,
    prompt_for_input,
)
from batchslicer.cli.menu import ask_number, choose, confirm
from batchslicer.cli.output_prompt import output_from_path, prompt_for_output
from batchslicer.cli.preset_prompt import choose_preset, find_preset, select_presets
from batchslicer.cli.profile_prompt import prompt_for_profile
from batchslicer.cli.send_prompt import prompt_for_printer
from batchslicer.cli.service import ServiceOptions, run_service
from batchslicer.cli.setup import SetupOptions, run_setup
from batchslicer.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer
from batchslicer.core.config import Config, find_config_file, get_config
from batchslicer.core.environment import EnvironmentService
from batchslicer.core.logging import configure_logging, current_log_file
from batchslicer.domain.filaments import (
    LoadedFilament,
    ProjectFilament,
    describe_project_slot,
    match_slots,
)
from batchslicer.domain.options import (
    COPYABLE_SUFFIXES,
    MAX_COPIES,
    SliceOptions,
    is_loaded_slot,
    slot_for,
)
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.domain.printers import PrinterHost, host_from_address, printer_hosts
from batchslicer.domain.profiles import LAST_RUN, Profile, Target, combine, is_valid_name
from batchslicer.infrastructure.printer_api import PrinterError
from batchslicer.infrastructure.printer_clients import client_for
from batchslicer.infrastructure.profiles import ProfileError, ProfileStore
from batchslicer.services.archives import ArchiveError, extract_models, is_archive
from batchslicer.services.filament_matching import FilamentMatcher, build_matcher
from batchslicer.services.gcode_stats import GcodeStats, format_duration
from batchslicer.services.report import write_report
from batchslicer.services.sending import SendingService, SendOutcome, SentFile, plan_uploads
from batchslicer.services.slicing import (
    BatchOutcome,
    ProgressCallback,
    SliceOutcome,
    SlicingService,
    Work,
    plan_work,
)
from batchslicer.services.watch_status import StatusWriter
from batchslicer.services.watching import DEFAULT_INTERVAL_SECONDS, WatchFolder, watch

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INTERRUPTED = 130
"""The conventional status for a program stopped with Ctrl+C."""

_REPORT_INTERVAL_SECONDS = 10.0
"""How often a running batch's report is rewritten."""

_HINTS = (
    (
        # OrcaSlicer 2.4 says the first; 2.5 names the reason, usually the second.
        ("Failed slicing the model", "empty first layer"),
        lambda options: options.orient == "off",
        "{count} model(s) failed in a way that is often down to how the part was "
        "saved (for example floating above the bed); --orient retry slices them again "
        "with the slicer's auto-orient.",
    ),
    (
        ("Unsupported 3MF version",),
        lambda options: not options.allow_newer_files,
        "{count} project(s) were saved by a newer slicer version; --allow-newer-files "
        "lets the slicer try them (or update the slicer).",
    ),
    (
        ("temperature difference of the filaments",),
        lambda options: True,
        "{count} multi-colour project(s) were given filaments that print at temperatures "
        "too far apart (such as PLA with PETG); choose filaments of one kind for all slots.",
    ),
)
"""(texts in a failure message, whether the hint applies, hint) for failures an option may fix."""


class _StartupFailed(Exception):
    """Raised when startup stops after its reason has already been shown."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run BatchSlicer with command-line ``argv`` and return a process exit status."""
    options = parse_arguments(argv)
    previous = _stop_on_terminate()
    try:
        if isinstance(options, SetupOptions):
            return _setup(options)
        if isinstance(options, DoctorOptions):
            return EXIT_SUCCESS if run_doctor(options) == 0 else EXIT_FAILURE
        if isinstance(options, ServiceOptions):
            return EXIT_SUCCESS if run_service(options) == 0 else EXIT_FAILURE
        return _run(options)
    except KeyboardInterrupt:
        _error("\nCancelled.")
        logging.getLogger("batchslicer").warning("Cancelled by the user.")
        return EXIT_INTERRUPTED
    except Exception as error:  # noqa: BLE001 - last-resort report for any bug
        return _report_unexpected(error)
    finally:
        _remove_unpacked()
        _restore_terminate(previous)


def _stop_on_terminate() -> object:
    """Treat a request to terminate (``kill``, ``systemctl stop``, launchd) like Ctrl+C.

    Slicers are then stopped and partial results removed, as on Ctrl+C,
    instead of the process ending mid-write. Returns the previous handler,
    or None when it cannot be set (not the main thread, or no SIGTERM).
    """
    def interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    try:
        return signal.signal(signal.SIGTERM, interrupt)
    except (ValueError, OSError, AttributeError):
        return None


def _restore_terminate(previous: object) -> None:
    """Put back the terminate handler that was there before :func:`_stop_on_terminate`."""
    if previous is not None:
        try:
            signal.signal(signal.SIGTERM, previous)  # type: ignore[arg-type]
        except (ValueError, OSError, AttributeError):
            pass


def _run(options: RunOptions) -> int:
    """Run the slicing workflow and return a process exit status."""
    listing = options.list_presets or options.list_profiles or options.delete_profile
    if not listing:
        print(get_banner(), end="")
    logger: logging.Logger | None = None

    try:
        if options.save_profile is not None and not is_valid_name(options.save_profile):
            raise ProfileError(
                f"Invalid profile name '{options.save_profile}': use letters, digits, "
                "spaces, dots, dashes and underscores (up to 64 characters)."
            )
        config = get_config(find_config_file(options.config))
        logger = configure_logging(log_directory=config.get_path("paths", "logs"))
        logger.info("Using configuration %s", config.path)
        profiles = ProfileStore(config.get_path("paths", "profiles"))
        if options.list_profiles:
            _list_profiles(profiles)
            return EXIT_SUCCESS
        if options.delete_profile is not None:
            deleted = profiles.delete(options.delete_profile)
            print(f"Deleted profile '{deleted.name}'.")
            return EXIT_SUCCESS
        watch_input = options.input  # only --input itself, never a profile's input, is watched
        options, specs, offered_more, from_profile = _plan_targets(options, profiles, logger)

        if options.list_presets:
            if len(specs) > 1:
                raise SlicerSelectionError("--list-presets works with one printer at a time.")
            spec = specs[0]
            slicer = _select_slicer(spec.slicer, options.no_prompt, config)
            _verify_environment(config, logger, slicer)
            _list_presets(slicer, _preset_library(slicer, config, logger), spec.printer)
            return EXIT_SUCCESS

        targets = _resolve_targets(specs, offered_more, options.no_prompt, config, logger)
        targets = _attach_printers(targets, specs, config)
        slice_options = SliceOptions(
            orient=options.orient or "off",
            allow_newer_files=bool(options.allow_newer_files),
            thumbnails=options.thumbnails is not False,
            plates=bool(options.plates),
            copies=options.copies or 1,
            slots=options.slots or (),
            flat=bool(options.flat),
        )
        jobs = options.jobs or 1
        _check_options(targets, slice_options)
        _show_ready(targets, slice_options, jobs, start=options.start)
        if options.watch:
            return _watch(
                replace(options, input=watch_input),
                targets,
                config,
                logger,
                profiles,
                slice_options,
                jobs,
                from_profile,
            )
        slice_input = _apply_exclude(_select_input(options, config, logger), options.exclude or ())
        if options.plates is None and not from_profile and not options.no_prompt:
            options = replace(options, plates=_ask_plates(targets, slice_input, profiles))
        if options.copies is None and not from_profile and not options.no_prompt:
            options = replace(options, copies=_ask_copies(targets, slice_input))
        options = replace(options, copies=_checked_copies(options.copies, slice_input, from_profile))
        slice_options = replace(
            slice_options,
            plates=bool(options.plates) and slice_input.is_folder,
            copies=options.copies or 1,
        )
        _check_options(targets, slice_options)
        if not from_profile and options.send is None and not options.no_prompt:
            targets = _ask_to_send(targets, profiles, config)
        if (
            not from_profile
            and not options.no_prompt
            and options.filament is None
            and options.loaded_filaments is None
        ):
            targets = _ask_filament_slots(targets, slice_input, logger)
            if any(target.match_loaded for target in targets):
                options = replace(options, loaded_filaments=True)
        _check_start(options.start, targets, slice_input)
        _check_slots(targets, slice_options, bool(options.loaded_filaments))
        if options.dry_run:
            planned_output = (options.output or config.get_path("paths", "output")).expanduser()
            return _dry_run(
                targets,
                slice_input,
                slice_options,
                planned_output.absolute(),
                logger,
                loaded_filaments=bool(options.loaded_filaments),
                start=options.start,
            )
        output_directory = _select_output(options, config)
        _check_printers(targets, logger)
        logger.info(
            "Selected %d model(s) from %s; output to %s",
            len(slice_input.models),
            slice_input.root,
            output_directory,
        )
        chosen = slice_input.root if slice_input.is_folder else slice_input.models[0]
        chosen = _UNPACKED.get(chosen, chosen)  # remember the zip, not its temporary folder
        _remember_choices(profiles, options, targets, chosen, output_directory, logger)
        return _slice_targets(
            targets,
            slice_input,
            output_directory,
            config,
            logger,
            slice_options,
            jobs,
            start=options.start,
            loaded_filaments=bool(options.loaded_filaments),
        )
    except _StartupFailed:
        return EXIT_FAILURE
    except (
        SlicerSelectionError,
        PresetError,
        ProfileError,
        PrinterError,
        FileNotFoundError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        _error(f"BatchSlicer startup failed: {error}")
        if logger is not None:
            logger.error("BatchSlicer startup failed: %s", error)
        return EXIT_FAILURE


def _error(message: str) -> None:
    """Show an error message on stderr."""
    print(message, file=sys.stderr)


def _report_unexpected(error: Exception) -> int:
    """Report an unexpected error briefly, with the full details in the log."""
    logger = logging.getLogger("batchslicer")
    log_file = current_log_file()
    if log_file is not None:
        logger.error("Unexpected error", exc_info=error)
        _error(f"BatchSlicer stopped because of an unexpected error: {type(error).__name__}: {error}")
        _error(f"Details were written to {log_file}. Please include them when reporting the problem.")
    else:
        _error("BatchSlicer stopped because of an unexpected error:")
        traceback.print_exception(error, file=sys.stderr)
    return EXIT_FAILURE


def _setup(options: SetupOptions) -> int:
    """Run ``batchslicer setup`` and return a process exit status."""
    print(get_banner(), end="")
    try:
        run_setup(options)
    except (SlicerSelectionError, OSError) as error:
        _error(f"BatchSlicer setup failed: {error}")
        return EXIT_FAILURE
    return EXIT_SUCCESS


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    """A target whose slicer and presets have been chosen and checked."""

    slicer: SlicerDefinition
    library: PresetLibrary | None
    selection: PresetSelection | None
    host: PrinterHost | None = None
    """The printer the G-code is sent to, if any."""

    match_loaded: bool = False
    """Match multi-colour projects to the filaments loaded in ``host`` (asked interactively)."""

    def describe(self) -> str:
        """Return the slicer and presets as one line."""
        if self.selection is None:
            return self.slicer.display_name
        filaments = " + ".join(preset.name for preset in self.selection.filaments)
        return (
            f"{self.slicer.display_name}: {self.selection.printer.name} / "
            f"{filaments} / {self.selection.process.name}"
        )

    def folder_name(self) -> str:
        """Return a folder name for this target's results in a multi-printer run."""
        name = self.selection.printer.name if self.selection else self.slicer.display_name
        return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or self.slicer.key

    def as_target(self) -> Target:
        """Return the choices to remember for this target."""
        return Target(
            slicer=self.slicer.key,
            printer=self.selection.printer.name if self.selection else None,
            filament=self.selection.filament.name if self.selection else None,
            process=self.selection.process.name if self.selection else None,
            send=self.host.name if self.host else None,
            more_filaments=(
                tuple(preset.name for preset in self.selection.more_filaments)
                if self.selection
                else ()
            ),
        )


def _plan_targets(
    options: RunOptions,
    profiles: ProfileStore,
    logger: logging.Logger,
) -> tuple[RunOptions, list[Target], bool, bool]:
    """Return the options with profile choices filled in, the targets to slice for,
    whether to offer adding more printers, and whether a profile was used.

    Profiles come from --profile/--last (several combine their printers), or one
    is offered interactively when nothing was given and profiles exist.
    Command-line slicer and preset options override a single target's choices.
    """
    chosen: list[Profile] = [profiles.get(name) for name in options.profiles]
    interactive = not options.no_prompt and not options.list_presets
    if not chosen and interactive and not options.has_choices():
        saved = profiles.load()
        if saved:
            picked = prompt_for_profile(saved)
            if picked is not None:
                chosen = [picked]

    targets = [Target()]
    if chosen:
        plan = combine("run", chosen)
        for profile in chosen:
            print(f"Using profile '{profile.name}': {profile.summary()}")
            logger.info("Using profile %s: %s", profile.name, profile.summary())
        targets = list(plan.targets)
        options = replace(
            options,
            input=options.input if options.input is not None else plan.input,
            output=options.output if options.output is not None else plan.output,
            orient=options.orient if options.orient is not None else plan.orient,
            allow_newer_files=(
                options.allow_newer_files
                if options.allow_newer_files is not None
                else plan.allow_newer_files
            ),
            jobs=options.jobs if options.jobs is not None else plan.jobs,
            exclude=options.exclude if options.exclude is not None else plan.exclude,
            thumbnails=options.thumbnails if options.thumbnails is not None else plan.thumbnails,
            plates=options.plates if options.plates is not None else plan.plates,
            copies=options.copies if options.copies is not None else plan.copies,
            loaded_filaments=(
                options.loaded_filaments
                if options.loaded_filaments is not None
                else plan.loaded_filaments
            ),
            slots=options.slots if options.slots is not None else plan.slots,
            flat=options.flat if options.flat is not None else plan.flat,
        )

    if len(targets) > 1:
        if options.has_target_choices():
            raise SlicerSelectionError(
                "--slicer, --printer, --filament, --process and --send describe one "
                "printer, so they cannot be combined with several printers. Save each "
                "printer as its own profile and list them with --profile."
            )
    else:
        base = targets[0]
        targets = [
            Target(
                slicer=options.slicer or base.slicer,
                printer=options.printer or base.printer,
                filament=options.filament or base.filament,
                process=options.process or base.process,
                send=options.send or base.send,
                more_filaments=options.more_filaments if options.filament else base.more_filaments,
            )
        ]
    if options.send == "":
        targets = [replace(target, send=None) for target in targets]
    offer_more = interactive and not options.profiles and not options.has_target_choices()
    return options, targets, offer_more, bool(chosen)


def _resolve_targets(
    specs: list[Target],
    offer_more: bool,
    no_prompt: bool,
    config: Config,
    logger: logging.Logger,
) -> list[_ResolvedTarget]:
    """Choose and check the slicer and presets for each target.

    Each slicer is checked once. When ``offer_more`` is true the user may add
    more printers after the planned ones.
    """
    resolved: list[_ResolvedTarget] = []
    libraries: dict[str, PresetLibrary | None] = {}
    pending = list(specs)
    while pending:
        spec = pending.pop(0)
        if resolved:
            print(f"Printer {len(resolved) + 1}:")
        slicer = _select_slicer(spec.slicer, no_prompt, config)
        logger.info("Selected slicer: %s", slicer.display_name)
        if slicer.key not in libraries:
            _verify_environment(config, logger, slicer)
            libraries[slicer.key] = _preset_library(slicer, config, logger)
        library = libraries[slicer.key]
        selection = _select_presets(spec, slicer, library, no_prompt, logger)
        resolved.append(_ResolvedTarget(slicer, library, selection))
        if not pending and offer_more and confirm(
            "Slice for another printer as well?", read_line=input, write=print, default=False
        ):
            pending.append(Target())
    return resolved


def _attach_printers(
    targets: list[_ResolvedTarget],
    specs: list[Target],
    config: Config,
) -> list[_ResolvedTarget]:
    """Return the targets with the printer each one sends to.

    ``--send`` names a printer in the configuration, or gives its address
    directly. Printers added interactively after the planned ones do not send.
    """
    names = [spec.send for spec in specs] + [None] * (len(targets) - len(specs))
    if not any(names):
        return targets
    hosts = printer_hosts(config.section("printers"))
    attached = []
    for target, name in zip(targets, names, strict=True):
        if name is None:
            attached.append(target)
            continue
        host = next((host for key, host in hosts.items() if key.casefold() == name.casefold()), None)
        if host is None:
            host = host_from_address(name)
        if host is None:
            known = ", ".join(sorted(hosts)) if hosts else "none are set up"
            raise SlicerSelectionError(
                f"No printer named '{name}' in the 'printers' section of {config.path} "
                f"(configured: {known}). Give the printer's address instead, for "
                "example --send 192.168.1.50"
            )
        attached.append(replace(target, host=host))
    return attached


def _ask_to_send(
    targets: list[_ResolvedTarget],
    profiles: ProfileStore,
    config: Config,
) -> list[_ResolvedTarget]:
    """Ask whether to send a one-printer run's G-code, when there is a printer to offer.

    Printers come from the configuration and from the last run. Nothing is
    asked when there are none, or when the run slices for several printers.
    """
    if len(targets) != 1 or targets[0].host is not None:
        return targets
    hosts = list(printer_hosts(config.section("printers")).values())
    last: PrinterHost | None = None
    try:
        previous = profiles.load().get(LAST_RUN)
    except ProfileError:
        previous = None
    if previous is not None and not previous.is_multi and previous.targets[0].send:
        name = previous.targets[0].send
        last = next((host for host in hosts if host.name.casefold() == name.casefold()), None)
        if last is None:
            try:
                last = host_from_address(name)
            except ValueError:
                last = None
    if not hosts and last is None:
        return targets
    chosen = prompt_for_printer(hosts, last=last)
    if chosen is None:
        return targets
    print(f"  Send to:  {chosen.describe()}")
    return [replace(targets[0], host=chosen)]


def _ask_copies(targets: list[_ResolvedTarget], slice_input: SliceInput) -> int | None:
    """Ask how many copies of a single model to slice, when copies are possible."""
    model = slice_input.models[0]
    if slice_input.is_folder or model.suffix.casefold() not in COPYABLE_SUFFIXES:
        return None
    if not all(target.slicer.supports("--clone-objects") for target in targets):
        return None
    return ask_number(
        f"How many copies of {model.name}?",
        default=1,
        minimum=1,
        maximum=MAX_COPIES,
        read_line=input,
        write=print,
    )


def _checked_copies(copies: int | None, slice_input: SliceInput, from_profile: bool) -> int | None:
    """Return the copies to slice, refusing them for a folder or a 3MF project.

    A profile's copies are left out (with a note) when this run's input cannot
    be copied; copies asked for on the command line stop the run instead.
    """
    if copies is None or copies <= 1:
        return copies
    model = slice_input.models[0]
    if slice_input.is_folder:
        problem = "--copies works with a single model file, not a folder (see --plates)."
    elif model.suffix.casefold() not in COPYABLE_SUFFIXES:
        problem = (
            f"--copies works with STL, OBJ or STEP models; {model.name} is a project "
            "that keeps its own plates."
        )
    else:
        return copies
    if from_profile:
        print(f"Not making {copies} copies: {problem}")
        return 1
    raise SlicerSelectionError(problem)


def _ask_plates(
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    profiles: ProfileStore,
) -> bool | None:
    """Ask whether to put each folder's models together on plates, when that is possible.

    Asked only for a folder with at least one subfolder holding two or more
    loose models, and only when every chosen slicer can arrange. Enter keeps
    what the last run did.
    """
    if not slice_input.is_folder or not all(t.slicer.supports("--arrange") for t in targets):
        return None
    counts: dict[Path, int] = {}
    for model in slice_input.models:
        if model.suffix.casefold() in (".stl", ".obj", ".step", ".stp"):
            counts[model.parent] = counts.get(model.parent, 0) + 1
    shared = {folder: count for folder, count in counts.items() if count > 1}
    if not shared:
        return None
    try:
        previous = profiles.load().get(LAST_RUN)
    except ProfileError:
        previous = None
    default = bool(previous is not None and previous.plates)
    models = sum(shared.values())
    folders = len(shared)
    return confirm(
        f"Put the models in each folder together on plates? ({models} models in {folders} "
        f"folder{'s' if folders != 1 else ''} could share plates; 3MF projects keep their own)",
        read_line=input,
        write=print,
        default=default,
    )


def _check_start(start: bool, targets: list[_ResolvedTarget], slice_input: SliceInput) -> None:
    """Stop before slicing if --start cannot be done for this run."""
    if not start:
        return
    if any(target.host is None for target in targets):
        raise SlicerSelectionError("--start needs --send PRINTER to know which printer to start.")
    if slice_input.is_folder:
        raise SlicerSelectionError(
            "--start prints one model, so it works with a single model file, not a folder."
        )


def _check_printers(targets: list[_ResolvedTarget], logger: logging.Logger) -> None:
    """Make sure every printer the G-code is sent to answers, before slicing starts."""
    checked: set[str] = set()
    for target in targets:
        if target.host is None or target.host.name in checked:
            continue
        checked.add(target.host.name)
        status = SendingService(client_for(target.host), logger=logger).check()
        print(f"Printer {target.host.describe()} answers{status.note()}.")


def _remember_choices(
    profiles: ProfileStore,
    options: RunOptions,
    targets: list[_ResolvedTarget],
    chosen_input: Path | None,
    output_directory: Path,
    logger: logging.Logger,
    *,
    remember_last: bool = True,
) -> None:
    """Save this run's choices as the last run (unless told not to), and as --save-profile if given."""
    choices = Profile(
        name=LAST_RUN,
        targets=tuple(target.as_target() for target in targets),
        input=chosen_input,
        output=output_directory,
        orient=options.orient,
        allow_newer_files=options.allow_newer_files,
        jobs=options.jobs,
        exclude=options.exclude,
        thumbnails=options.thumbnails,
        plates=options.plates,
        copies=options.copies,
        loaded_filaments=options.loaded_filaments,
        slots=options.slots,
        flat=options.flat,
    )
    if remember_last:
        try:
            profiles.save(choices)
        except ProfileError as error:
            logger.warning("Could not remember this run: %s", error)
    if options.save_profile is not None:
        profiles.save(replace(choices, name=options.save_profile))
        print(f"Saved these choices as profile '{options.save_profile}'.")
        logger.info("Saved profile %s", options.save_profile)


def _watch(
    options: RunOptions,
    targets: list[_ResolvedTarget],
    config: Config,
    logger: logging.Logger,
    profiles: ProfileStore,
    slice_options: SliceOptions,
    jobs: int,
    from_profile: bool,
) -> int:
    """Slice every model or folder put in the watched folder until Ctrl+C.

    The watched folder is ``--input`` as given on the command line, or the
    configured incoming folder; a profile's input is never watched, because
    watching moves what it slices. The questions an interactive run asks about the input (plates, sending,
    output) are asked once, before watching starts. Each drop is sliced like
    a run of its own, then moved into the folder's ``sliced`` or ``failed``
    subfolder. Watch runs are not remembered as the last run.
    """
    folder = (options.input or config.get_path("paths", "incoming")).expanduser().absolute()
    if folder.exists() and not folder.is_dir():
        raise SlicerSelectionError(f"--watch needs a folder to watch; {folder} is a file.")
    can_arrange = all(target.slicer.supports("--arrange") for target in targets)
    if options.plates is None and not from_profile and not options.no_prompt and can_arrange:
        options = replace(options, plates=_ask_watch_plates(profiles))
    copies = options.copies or 1
    slice_options = replace(slice_options, plates=bool(options.plates), copies=copies)
    _check_options(targets, slice_options)
    if not from_profile and options.send is None and not options.no_prompt:
        targets = _ask_to_send(targets, profiles, config)
    _check_slots(targets, slice_options, bool(options.loaded_filaments))
    output_directory = _select_output(options, config)
    resolved_output = output_directory.expanduser().absolute()
    if resolved_output.is_relative_to(folder) or folder.is_relative_to(resolved_output):
        raise SlicerSelectionError(
            f"The output folder {output_directory} and the watched folder {folder} must be "
            "separate, not one inside the other."
        )
    _check_printers(targets, logger)
    if options.save_profile is not None:
        _remember_choices(profiles, options, targets, None, output_directory, logger, remember_last=False)

    watched = WatchFolder(folder, logger=logger)
    progress = StatusWriter(
        folder,
        output_directory.expanduser().absolute(),
        on_error=lambda error: logger.warning("Could not write the watch status file: %s", error),
    )
    progress.watching()
    print("")
    print(f"Watching {folder} for models; output to {output_directory}.")
    print(
        f"Put a model file, a zip file or a folder of models in it. When it has finished copying it is "
        f"sliced, then moved to {watched.sliced.name}/ (or {watched.failed.name}/ if any "
        f"model failed). {_how_to_stop()}",
        flush=True,
    )
    logger.info("Watching %s; output to %s", folder, output_directory)
    if copies > 1:
        print(f"Single STL, OBJ or STEP models get {copies} copies; folders and 3MF projects get one.")

    def handle(drop: Path) -> bool:
        print("")
        print(f"=== {drop.name} ===", flush=True)
        logger.info("Slicing %s from the watched folder", drop)
        progress.slicing(drop.name)

        def on_model(number: int, count: int, model: Path) -> None:
            shown = model.relative_to(drop).as_posix() if model.is_relative_to(drop) else model.name
            progress.progress(number, count, "" if shown == "." else shown)

        try:
            slice_input = _apply_exclude(_input_from(drop, config, logger), options.exclude or ())
            single = not slice_input.is_folder
            copyable = single and slice_input.models[0].suffix.casefold() in COPYABLE_SUFFIXES
            drop_options = replace(
                slice_options,
                plates=slice_options.plates and slice_input.is_folder,
                copies=copies if copyable else 1,
            )
            status = _slice_targets(
                targets, slice_input, output_directory, config, logger, drop_options, jobs,
                loaded_filaments=bool(options.loaded_filaments),
                on_model=on_model,
            )
        except (SlicerSelectionError, PresetError, PrinterError, OSError, ValueError) as error:
            _error(f"Could not slice {drop.name}: {error}")
            logger.error("Could not slice %s: %s", drop, error)
            return False
        finally:
            _remove_unpacked()  # a dropped zip's temporary folder goes as soon as it is done
        if status == EXIT_INTERRUPTED:
            raise KeyboardInterrupt
        return status == EXIT_SUCCESS

    def on_moved(drop: Path, moved: Path | None, success: bool) -> None:
        progress.finished(
            drop.name, success=success, moved_to=moved.relative_to(folder).as_posix() if moved else ""
        )
        if moved is None:
            _error(f"Could not move {drop.name} out of the watched folder; it will not be sliced again.")
        else:
            print(f"Moved {drop.name} to {moved.relative_to(folder).as_posix()}")
        print("Watching for more models...", flush=True)

    try:
        summary = watch(
            watched, handle, interval=DEFAULT_INTERVAL_SECONDS, sleep=time.sleep, on_moved=on_moved
        )
    finally:
        progress.stopped()
    print("")
    print(f"Stopped watching. Sliced {summary.sliced}, failed {summary.failed}.")
    logger.info("Stopped watching %s: %d sliced, %d failed", folder, summary.sliced, summary.failed)
    return EXIT_SUCCESS


def _how_to_stop() -> str:
    """Return how to stop watching: Ctrl+C in a terminal, stopping the service otherwise."""
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False
    if interactive:
        return "Press Ctrl+C to stop."
    return "It runs until it is stopped (for a background service: batchslicer service uninstall)."


def _ask_watch_plates(profiles: ProfileStore) -> bool:
    """Ask whether folders dropped in should have their models put together on plates."""
    try:
        previous = profiles.load().get(LAST_RUN)
    except ProfileError:
        previous = None
    return confirm(
        "When a folder is put in, put the models in each of its folders together on plates?",
        read_line=input,
        write=print,
        default=bool(previous is not None and previous.plates),
    )


def _list_profiles(profiles: ProfileStore) -> None:
    """Print the saved profiles, the last run first."""
    saved = profiles.load()
    if not saved:
        print(f"No saved profiles yet ({profiles.path}).")
        return
    print(f"Saved profiles ({profiles.path}):")
    for profile in sorted(
        saved.values(), key=lambda item: (item.name != LAST_RUN, item.name.casefold())
    ):
        name = f"{profile.name} (used by --last)" if profile.name == LAST_RUN else profile.name
        print(f"  {name}: {profile.summary()}")


def _select_slicer(key: str | None, no_prompt: bool, config: Config) -> SlicerDefinition:
    """Return the named slicer, or ask for one."""
    configured = [slicer for slicer in SLICERS if is_configured(slicer, config)]
    if key is not None:
        slicer = get_slicer(key)
        if slicer not in configured:
            raise SlicerSelectionError(
                f"{slicer.display_name} is not configured. Set {slicer.key}.executable "
                f"and {slicer.key}.datadir in {config.path}."
            )
        return slicer
    if no_prompt:
        raise SlicerSelectionError("--slicer is required when --no-prompt is used.")
    return prompt_for_slicer(SLICERS, configured)


def _verify_environment(
    config: Config,
    logger: logging.Logger,
    slicer: SlicerDefinition,
) -> None:
    """Run the environment checks, showing each failure and stopping if any fail."""
    results = EnvironmentService(config=config, logger=logger, slicer=slicer).run_checks()
    failed = [result for result in results if not result.passed]
    if failed:
        logger.error("BatchSlicer startup failed environment verification.")
        _error("BatchSlicer startup failed: environment verification failed.")
        for result in failed:
            _error(f"  - {result.name}: {result.message}")
        raise _StartupFailed


def _preset_library(
    slicer: SlicerDefinition,
    config: Config,
    logger: logging.Logger,
) -> PresetLibrary | None:
    """Return the slicer's preset library, or None if presets are not supported for it."""
    if not slicer.supports_preset_selection:
        return None
    data_directory = config.get_path(slicer.key, "datadir")
    system_directory = find_system_profiles(
        config.get_program(slicer.key),
        data_directory,
        config.get_path("paths", "data") / "slicer-profiles",
        logger=logger,
    )
    return PresetLibrary(
        data_directory,
        str(slicer.app_config_name),
        system_directory=system_directory,
        logger=logger,
    )


def _select_presets(
    spec: Target,
    slicer: SlicerDefinition,
    library: PresetLibrary | None,
    no_prompt: bool,
    logger: logging.Logger,
) -> PresetSelection | None:
    """Return the presets named for the target, asking for any not named."""
    named = [spec.printer, spec.filament, spec.process]
    if library is None:
        if any(name is not None for name in named):
            raise SlicerSelectionError(
                f"Preset selection is not available for {slicer.display_name} yet; "
                "remove --printer, --filament and --process."
            )
        print(f"Preset selection is not available for {slicer.display_name} yet.")
        return None

    selection = select_presets(
        library,
        printer=spec.printer,
        filament=spec.filament,
        process=spec.process,
        prompt=not no_prompt,
    )
    if spec.more_filaments:
        compatible = library.filaments_for(selection.printer)
        selection = replace(
            selection,
            more_filaments=tuple(
                find_preset(PresetKind.FILAMENT, compatible, name, printer=selection.printer)
                for name in spec.more_filaments
            ),
        )
    logger.info(
        "Selected presets: printer=%s, filament=%s, process=%s",
        selection.printer.name,
        " + ".join(preset.name for preset in selection.filaments),
        selection.process.name,
    )
    return selection


def _list_presets(
    slicer: SlicerDefinition,
    library: PresetLibrary | None,
    printer_name: str | None,
) -> None:
    """Print preset names usable with --printer, --filament and --process."""
    if library is None:
        raise SlicerSelectionError(
            f"Preset selection is not available for {slicer.display_name} yet."
        )
    if printer_name is None:
        print(f"Printers for {slicer.display_name} (use with --printer):")
        _print_names(library.printers())
        return
    printer = find_preset(PresetKind.PRINTER, library.printers(), printer_name)
    print(f"Filaments for {printer.name} (use with --filament):")
    _print_names(library.filaments_for(printer))
    print(f"Processes for {printer.name} (use with --process):")
    _print_names(library.processes_for(printer))


def _print_names(presets: Sequence[Preset]) -> None:
    """Print one preset name per line, marking the user's own presets."""
    for preset in presets:
        mine = "  (mine)" if preset.is_user else ""
        print(f"  {preset.name}{mine}")


def _check_options(targets: list[_ResolvedTarget], options: SliceOptions) -> None:
    """Stop before slicing if a chosen slicer cannot do what the options ask."""
    for target in targets:
        if options.copies > 1 and not target.slicer.supports("--clone-objects"):
            raise SlicerSelectionError(
                f"{target.slicer.display_name} cannot make copies from its command line, "
                "so --copies cannot be used with it."
            )
        if options.plates and not target.slicer.supports("--arrange"):
            raise SlicerSelectionError(
                f"{target.slicer.display_name} cannot arrange models from its command line, "
                "so --plates cannot be used with it."
            )
        if options.orient != "off" and not target.slicer.supports("--orient"):
            raise SlicerSelectionError(
                f"{target.slicer.display_name} has no command-line auto-orient, so "
                "--orient cannot be used with it."
            )


def _check_slots(
    targets: list[_ResolvedTarget], options: SliceOptions, loaded_filaments: bool
) -> None:
    """Stop before slicing if a --slot names a filament that will not be there."""
    numbers = [int(slot) for _, slot in options.slots if not is_loaded_slot(slot)]
    loaded = [slot for _, slot in options.slots if is_loaded_slot(slot)]
    for target in targets:
        given = len(target.selection.filaments) if target.selection else 1
        if numbers and max(numbers) > given:
            raise SlicerSelectionError(
                f"--slot {max(numbers)} needs at least {max(numbers)} filaments, but "
                f"{target.describe()} has {given}; give --filament once per slot, slot 1 first."
            )
        uses_loaded = loaded_filaments or target.match_loaded
        if loaded and (not uses_loaded or target.host is None):
            raise SlicerSelectionError(
                f"--slot {loaded[0]} names a loaded filament, which needs --loaded-filaments "
                "and --send PRINTER."
            )


def _show_ready(
    targets: list[_ResolvedTarget],
    options: SliceOptions | None = None,
    jobs: int = 1,
    *,
    start: bool = False,
) -> None:
    """Show the slicer(s), presets and slicing options that will be used."""
    if len(targets) > 1:
        print(f"BatchSlicer ready. Slicing for {len(targets)} printers:")
        for number, target in enumerate(targets, start=1):
            sends = f" -> send to {target.host.name}" if target.host else ""
            print(f"  {number}) {target.describe()}{sends}")
    else:
        target = targets[0]
        print(f"BatchSlicer ready. Slicer: {target.slicer.display_name}.")
        if target.selection is not None:
            print(f"  Printer:  {target.selection.printer.name}")
            filaments = target.selection.filaments
            if len(filaments) == 1:
                print(f"  Filament: {filaments[0].name}")
            else:
                print("  Filaments:")
                for slot, preset in enumerate(filaments, start=1):
                    print(f"    slot {slot}: {preset.name}")
            print(f"  Process:  {target.selection.process.name}")
        if target.host is not None:
            then = ", then start printing" if start else ""
            print(f"  Send to:  {target.host.describe()}{then}")
    extras = [options.describe()] if options is not None and options.describe() else []
    if jobs > 1:
        extras.append(f"{jobs} models at a time")
    if extras:
        print(f"  Options:  {', '.join(extras)}")
    cores = os.cpu_count() or 1
    if jobs > cores:
        print(f"  Note: --jobs {jobs} is more than this computer's {cores} cores; it may be slower.")


def _slice_targets(
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    output_directory: Path,
    config: Config,
    logger: logging.Logger,
    options: SliceOptions | None = None,
    jobs: int = 1,
    *,
    start: bool = False,
    loaded_filaments: bool = False,
    on_model: ProgressCallback | None = None,
) -> int:
    """Slice the input for every target and return the run's exit status.

    With several targets, each one's results go into its own subfolder of the
    output folder, named after the printer. A target with a printer to send to
    has its G-code sent once it is sliced. With ``loaded_filaments``, the
    filaments loaded in that printer are read first, and multi-colour projects
    are matched to them. ``on_model(number, count, model)`` is called as each
    model (or folder sliced together on plates) starts.
    """
    multi = len(targets) > 1
    folders = _unique_folder_names(targets) if multi else [""]
    results: list[tuple[_ResolvedTarget, bool]] = []
    for number, (target, folder) in enumerate(zip(targets, folders, strict=True), start=1):
        destination = output_directory / folder if multi else output_directory
        if multi:
            print("")
            print(f"=== Printer {number} of {len(targets)}: {target.describe()} ===")
        backend = OrcaBackend(slicer=target.slicer, config=config, logger=logger)
        matcher = (
            _filament_matcher(target, logger)
            if loaded_filaments or target.match_loaded
            else None
        )
        service = SlicingService(
            backend, presets=target.library, logger=logger, options=options, matcher=matcher
        )
        if slice_input.is_folder:
            batch = _slice_folder(
                service, slice_input, destination, target.selection, jobs, on_model=on_model
            )
            _report_batch(batch, slice_input.root, options or SliceOptions())
            _report_matches(matcher, slice_input.root)
            if batch.interrupted:
                skipped = len(targets) - number
                if skipped:
                    _error(f"{skipped} more printer(s) were not started.")
                return EXIT_INTERRUPTED
            sent = _send(target, batch.outcomes, destination, logger)
            results.append((target, not batch.failed and sent))
        else:
            model = slice_input.models[0]
            print(f"Slicing {model.name} with {target.slicer.display_name}...")
            if on_model is not None:
                on_model(1, 1, model)
            outcome = service.slice(model, destination, target.selection)
            _report(outcome, options or SliceOptions())
            _report_matches(matcher, slice_input.root)
            sent = _send(target, [outcome], destination, logger, start=start)
            results.append((target, outcome.success and sent))

    if multi:
        succeeded = sum(1 for _, ok in results if ok)
        print("")
        print(f"Finished {len(results)} printers: {succeeded} without problems.")
        for target, ok in results:
            print(f"  {'ok    ' if ok else 'FAILED'} {target.describe()}")
    return EXIT_SUCCESS if all(ok for _, ok in results) else EXIT_FAILURE


_MAX_PROJECTS_CHECKED = 2000
"""How many 3MF files are looked into for the multi-colour question."""


def _multi_colour_projects(slice_input: SliceInput) -> list[tuple[Path, tuple[ProjectFilament, ...]]]:
    """Return the input's 3MF projects listing filaments of different colours or materials.

    The one listing the most filaments comes first.
    """
    projects = []
    models = [model for model in slice_input.models if model.suffix.casefold() == ".3mf"]
    for model in models[:_MAX_PROJECTS_CHECKED]:
        slots = project_filaments(model)
        kinds = {(slot.colour.casefold(), slot.material.casefold()) for slot in slots}
        if len(slots) > 1 and len(kinds) > 1:
            projects.append((model, slots))
    return sorted(projects, key=lambda item: -len(item[1]))


def _ask_filament_slots(
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    logger: logging.Logger,
) -> list[_ResolvedTarget]:
    """Ask how to fill the filament slots when the input has a multi-colour project.

    Offered for each printer: matching the colours to the filaments loaded in
    the printer it sends to (when it reports any), the chosen filament in every
    slot, or a filament chosen for each slot.
    """
    projects = _multi_colour_projects(slice_input)
    if not projects:
        return targets
    model, slots = projects[0]
    print("")
    more = f" (of {len(projects)} multi-colour projects, the one with the most)" if len(projects) > 1 else ""
    print(f"{_label(model, slice_input.root)} lists {len(slots)} filaments{more}:")
    for number, slot in enumerate(slots, start=1):
        print(f"  slot {number}: {describe_project_slot(slot)}")
    answered = []
    for target in targets:
        if target.selection is None or target.library is None:
            answered.append(target)
            continue
        answered.append(_fill_slots(target, slots, len(targets) > 1, logger))
    return answered


def _fill_slots(
    target: _ResolvedTarget,
    slots: Sequence[ProjectFilament],
    several: bool,
    logger: logging.Logger,
) -> _ResolvedTarget:
    """Ask one printer's way of filling the slots and return it with the answer."""
    if target.selection is None or target.library is None:
        return target
    loaded: list[LoadedFilament] = []
    if target.host is not None:
        try:
            loaded = client_for(target.host).loaded_filaments()
        except PrinterError as error:
            logger.warning("Could not read loaded filaments from %s: %s", target.host.name, error)
    ways: list[tuple[str, str]] = []
    if loaded and target.host is not None:
        names = ", ".join(filament.describe() for filament in loaded)
        ways.append(("loaded", f"Match them to the filaments loaded in {target.host.name} ({names})"))
    ways.append(("same", f"Use {target.selection.filament.name} in every slot"))
    ways.append(("choose", "Choose a filament for each slot"))
    where = f" for {target.selection.printer.name}" if several else ""
    way = choose(
        ways,
        noun="way to fill the slots",
        plural="ways to fill the slots",
        label=lambda item: item[1],
        read_line=input,
        write=print,
        prompt="Number: ",
        heading=f"How should the filament slots be filled{where}?",
    )[0]
    if way == "loaded":
        return replace(target, match_loaded=True)
    if way == "same":
        return target
    compatible = target.library.filaments_for(target.selection.printer)
    print(f"Slot 1 uses {target.selection.filament.name}.")
    chosen = []
    for number, slot in enumerate(slots[1:], start=2):
        print(f"Filament for slot {number} ({describe_project_slot(slot)}):")
        chosen.append(choose_preset(PresetKind.FILAMENT, compatible, input, print))
    return replace(target, selection=replace(target.selection, more_filaments=tuple(chosen)))


def _dry_run(
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    options: SliceOptions,
    output_directory: Path,
    logger: logging.Logger,
    *,
    loaded_filaments: bool,
    start: bool,
) -> int:
    """Show what the run would do, without slicing, writing or sending anything.

    Printers are asked whether they answer and what is loaded (both only
    read). Choices are not remembered.
    """
    logger.info("Dry run for %d model(s) from %s", len(slice_input.models), slice_input.root)
    print("")
    print("Dry run: nothing is sliced, written or sent.")
    for number, target in enumerate(targets, start=1):
        print("")
        if len(targets) > 1:
            print(f"=== Printer {number} of {len(targets)}: {target.describe()} ===")
        loaded: list[LoadedFilament] = []
        if target.host is not None:
            client = client_for(target.host)
            try:
                status = client.status()
                print(f"Printer {target.host.describe()} answers{status.note()}.")
                if loaded_filaments or target.match_loaded:
                    loaded = client.loaded_filaments()
            except PrinterError as error:
                print(f"Printer {target.host.describe()} does not answer now: {error}")
        work = plan_work(slice_input.models, options.plates) if slice_input.is_folder else [
            Work(slice_input.models)
        ]
        total = len(slice_input.models)
        print(f"Would slice {total} model file{'s' if total != 1 else ''} from {_shown(slice_input.root)}:")
        for item in work:
            for line in _planned(item, slice_input, target, options, loaded):
                print(f"  {line}")
        layout = (
            "all G-code in that one folder" if options.flat and slice_input.is_folder
            else "one folder per model, mirroring the input" if slice_input.is_folder
            else "with the G-code inside"
        )
        name = slice_input.root.name if slice_input.is_folder else slice_input.models[0].stem
        folder = output_directory / (_unique_folder_names(targets)[number - 1] if len(targets) > 1 else "")
        print(f"Results would go to {folder / (name + '-<date>-<time>')} ({layout}).")
        if target.host is not None:
            starting = (
                ", then start printing it" if start and not slice_input.is_folder else ""
            )
            print(f"Then the G-code would be sent to {target.host.describe()}{starting}.")
    print("")
    print("Run the same command without --dry-run to do it.")
    return EXIT_SUCCESS


def _planned(
    item: Work,
    slice_input: SliceInput,
    target: _ResolvedTarget,
    options: SliceOptions,
    loaded: Sequence[LoadedFilament],
) -> list[str]:
    """Return what would happen to one job of a dry run, as lines."""
    root = slice_input.root
    if item.folder is not None:
        names = ", ".join(model.name for model in item.models)
        lines = [f"{_label(item.folder, root)}: {len(item.models)} models ({names})"]
        if options.slots:
            lines += [
                f"    {model.name}: {_slot_text(slot_for(model, root, options.slots), target, loaded)}"
                for model in item.models
            ]
        return lines
    model = item.models[0]
    label = _label(model, root)
    if not target.slicer.presets_in_projects and target.selection is not None and is_project(model):
        return [f"{label}: would fail ({target.slicer.display_name} cannot use your presets for a 3MF project)"]
    notes = []
    loose = model.suffix.casefold() in COPYABLE_SUFFIXES
    if loose and options.copies > 1 and not slice_input.is_folder:
        notes.append(f"{options.copies} copies")
    if loose and options.slots:
        notes.append(_slot_text(slot_for(model, root, options.slots), target, loaded))
    lines = [label + (f": {', '.join(notes)}" if notes else "")]
    slots = project_filaments(model)
    if len(slots) > 1:
        lines.append(f"    multi-colour project with {len(slots)} filaments:")
        if loaded:
            choice = match_slots(slots, loaded)
            lines += [
                f"      slot {n} ({describe_project_slot(slot)}) -> {loaded[i].describe()}"
                for n, (slot, i) in enumerate(zip(slots, choice, strict=True), start=1)
            ]
        elif target.selection is not None:
            chosen = target.selection.filaments
            lines += [
                f"      slot {n} ({describe_project_slot(slot)}) -> {chosen[min(n, len(chosen)) - 1].name}"
                for n, slot in enumerate(slots, start=1)
            ]
    return lines


def _slot_text(slot: str, target: _ResolvedTarget, loaded: Sequence[LoadedFilament]) -> str:
    """Return a --slot slot as shown in a dry run: the filament it means, where known."""
    if is_loaded_slot(slot):
        match = next((item for item in loaded if item.slot.casefold() == slot.casefold()), None)
        return match.describe() if match is not None else f"loaded filament {slot}"
    filaments = target.selection.filaments if target.selection is not None else ()
    if int(slot) <= len(filaments):
        return f"slot {slot} ({filaments[int(slot) - 1].name})"
    return f"slot {slot}"


def _filament_matcher(target: _ResolvedTarget, logger: logging.Logger) -> FilamentMatcher | None:
    """Return a matcher for the filaments loaded in the target's printer, or None (saying why)."""
    if target.host is None or target.library is None or target.selection is None:
        print("Not matching colours to loaded filaments: that needs --send PRINTER and presets.")
        return None
    try:
        loaded = client_for(target.host).loaded_filaments()
    except PrinterError as error:
        _error(f"Could not read the filaments loaded in {target.host.name}: {error}")
        logger.warning("Could not read loaded filaments from %s: %s", target.host.name, error)
        return None
    matcher = build_matcher(loaded, target.library, target.selection, logger=logger)
    if matcher is None:
        print(f"{target.host.name} reports no loaded filaments; using the chosen filaments.")
        return None
    print(f"Filaments loaded in {target.host.name}:")
    for item in matcher.loaded:
        print(f"  {item.loaded.describe()}  (sliced as {item.preset.name})")
    return matcher


def _report_matches(matcher: FilamentMatcher | None, root: Path) -> None:
    """Show which loaded filament each slot of each multi-colour project uses."""
    if matcher is None or not matcher.matches:
        return
    print("Colours matched to the loaded filaments:")
    for model, lines in matcher.matches.items():
        print(f"  {_label(model, root)}:")
        for line in lines:
            print(f"    {line}")


def _send(
    target: _ResolvedTarget,
    outcomes: Sequence[SliceOutcome],
    destination: Path,
    logger: logging.Logger,
    *,
    start: bool = False,
) -> bool:
    """Send the target's G-code to its printer, if it has one; return whether all arrived."""
    if target.host is None:
        return True
    uploads = plan_uploads(outcomes, destination)
    if not uploads:
        print(f"Nothing to send to {target.host.name}: no model sliced.")
        return True
    total = len(uploads)
    print(f"Sending {total} G-code file{'s' if total != 1 else ''} to {target.host.describe()}...")

    def on_result(number: int, count: int, result: SentFile) -> None:
        state = "sent" if result.success else f"FAILED: {result.error}"
        print(f"  [{number}/{count}] {result.upload.remote_path} ... {state}", flush=True)

    if start and any(len(item.stats.used_filaments()) > 1 for item in outcomes):
        print(
            "  Not starting it: start a multi-colour print on the printer's screen, where you "
            "can check which CFS slot each colour comes from."
        )
        start = False
    service = SendingService(client_for(target.host), logger=logger)
    outcome = service.send(uploads, start=start, on_result=on_result)
    _report_sending(outcome, start)
    return not outcome.failed


def _report_sending(outcome: SendOutcome, start: bool) -> None:
    """Summarise sending: how many files arrived and whether printing started."""
    total = len(outcome.files)
    print(f"Sent {len(outcome.sent)} of {total} file{'s' if total != 1 else ''} to {outcome.host.name}.")
    if outcome.failed:
        _error(f"  {len(outcome.failed)} file(s) did not reach {outcome.host.name}; see above.")
    if not start or not outcome.sent:
        return
    if total > 1:
        print(f"  Not started: the model gave {total} G-code files (plates); start one on the printer.")
    elif outcome.sent[0].print_started:
        print(f"  Printing {outcome.sent[0].remote_path} on {outcome.host.name}.")
    elif outcome.sent[0].print_queued:
        print(f"  {outcome.host.name} is busy; the print was added to its job queue.")
    else:
        print(
            f"  Not started: {outcome.host.name} did not start the print (it may be busy "
            "or not ready). The file is on the printer."
        )


def _unique_folder_names(targets: list[_ResolvedTarget]) -> list[str]:
    """Return one output subfolder name per target.

    A printer used with more than one slicer gets the slicer's name added;
    any remaining repeats (same printer and slicer twice) are numbered.
    """
    slicers_by_printer: dict[str, set[str]] = {}
    for target in targets:
        slicers_by_printer.setdefault(target.folder_name().casefold(), set()).add(target.slicer.key)

    names: list[str] = []
    for target in targets:
        base = target.folder_name()
        if len(slicers_by_printer[base.casefold()]) > 1:
            base = f"{base} ({target.slicer.display_name})"
        name, count = base, 2
        while name.casefold() in (existing.casefold() for existing in names):
            name = f"{base} ({count})"
            count += 1
        names.append(name)
    return names


_UNPACKED: dict[Path, Path] = {}
"""Temporary folders holding unpacked zip files, and the zip each came from."""


def _input_from(path: Path, config: Config, logger: logging.Logger) -> SliceInput:
    """Return the models in ``path``: a model file, a folder, or a zip file (unpacked first).

    A zip is unpacked into a temporary folder in BatchSlicer's data folder,
    removed again by :func:`_remove_unpacked`.
    """
    if not is_archive(path.expanduser()):
        return input_from_path(path)
    path = path.expanduser().absolute()
    work = config.get_path("paths", "data") / "unzipped"
    work.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="unzip-", dir=work))
    try:
        folder = extract_models(path, temporary)
    except ArchiveError as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise SlicerSelectionError(str(error)) from error
    _UNPACKED[folder] = path
    logger.info("Unpacked the models of %s into %s", path, folder)
    print(f"Unpacked {path.name}.")
    return input_from_path(folder)


def _shown(root: Path) -> Path | str:
    """Return the input as shown to the user: the zip's name, not its temporary folder."""
    archive = _UNPACKED.get(root)
    return archive.name if archive is not None else root


def _remove_unpacked(folder: Path | None = None) -> None:
    """Remove the temporary folder of one unpacked zip, or of all of them."""
    for unpacked in [folder] if folder is not None else list(_UNPACKED):
        if unpacked in _UNPACKED:
            shutil.rmtree(unpacked.parent, ignore_errors=True)
            del _UNPACKED[unpacked]


def _select_input(options: RunOptions, config: Config, logger: logging.Logger) -> SliceInput:
    """Return the models given with --input (a zip file is unpacked), or ask what to slice."""
    if options.input is not None:
        return _input_from(options.input, config, logger)
    if options.no_prompt:
        raise SlicerSelectionError("--input is required when --no-prompt is used.")
    return prompt_for_input(config.get_path("paths", "incoming"))


def _apply_exclude(slice_input: SliceInput, patterns: Sequence[str]) -> SliceInput:
    """Leave out the models matching --exclude, saying how many, and stop if none remain."""
    kept, skipped = exclude_models(slice_input, patterns)
    if skipped:
        print(
            f"Skipping {skipped} model file{'s' if skipped != 1 else ''} matching "
            f"--exclude {' '.join(patterns)}"
        )
        logging.getLogger("batchslicer").info(
            "Excluded %d model(s) matching %s", skipped, ", ".join(patterns)
        )
    if slice_input.is_folder and not kept.models:
        raise SlicerSelectionError(
            f"Every model file in {slice_input.root} matches --exclude {' '.join(patterns)}."
        )
    return kept


def _select_output(options: RunOptions, config: Config) -> Path:
    """Return the --output folder, the default folder without prompts, or ask."""
    if options.output is not None:
        return output_from_path(options.output)
    default = config.get_path("paths", "output")
    if options.no_prompt:
        return output_from_path(default)
    return prompt_for_output(default)


def _slice_folder(
    service: SlicingService,
    slice_input: SliceInput,
    output_directory: Path,
    selection: PresetSelection | None,
    jobs: int = 1,
    *,
    on_model: ProgressCallback | None = None,
) -> BatchOutcome:
    """Slice every model in the chosen folder, showing progress as it goes.

    One model at a time shows each model as it starts; with several at once,
    each model is shown as it finishes. The batch report is kept up to date.
    """
    total = len(slice_input.models)
    print(f"Slicing {total} model file{'s' if total != 1 else ''} from {_shown(slice_input.root)}...")
    finished: list[SliceOutcome] = []
    last_report = time.monotonic()

    open_line: Path | None = None  # the model or folder whose progress line awaits its result

    def on_start(number: int, count: int, model: Path) -> None:
        nonlocal open_line
        if on_model is not None:
            on_model(number, count, model)
        if jobs == 1:
            print(f"  [{number}/{count}] {_label(model, slice_input.root)} ... ", end="", flush=True)
            open_line = model

    def on_result(number: int, count: int, outcome: SliceOutcome) -> None:
        nonlocal last_report, open_line
        if open_line is not None and open_line != outcome.model:
            # Not every model of a folder could share plates; each is listed.
            print("not every part could share plates:")
            open_line = None
        if open_line is None:
            print(f"  [{number}/{count}] {_label(outcome.model, slice_input.root)} ... ", end="")
        open_line = None
        print(_result_text(outcome), flush=True)
        finished.append(outcome)
        if time.monotonic() - last_report >= _REPORT_INTERVAL_SECONDS:
            last_report = time.monotonic()
            _write_report(finished, outcome.job_directory, slice_input.root, output_directory)

    return service.slice_batch(
        slice_input.models,
        slice_input.root,
        output_directory,
        selection,
        jobs=jobs,
        on_start=on_start,
        on_result=on_result,
    )


def _write_report(
    outcomes: Sequence[SliceOutcome],
    job_directory: Path,
    root: Path,
    output_directory: Path,
) -> None:
    """Rewrite a running batch's report in its batch folder (found from a job folder)."""
    base = output_directory.absolute()
    batch_directory = base / job_directory.relative_to(base).parts[0]
    try:
        write_report(outcomes, batch_directory, root)
    except (OSError, ValueError) as error:
        logging.getLogger("batchslicer").warning("Could not update the report: %s", error)


def _label(model: Path, root: Path) -> str:
    """Return a model (or a folder sliced together on plates) as shown in progress lines."""
    relative = model.relative_to(root)
    if model == root or model.is_dir():
        name = model.name if model == root else relative.as_posix()
        return f"{name}/ (models together on plates)"
    return relative.as_posix()


def _result_text(outcome: SliceOutcome) -> str:
    """Return how one model (or plate group) in a batch went, as shown after its name."""
    if outcome.success:
        oriented = ", auto-oriented" if outcome.auto_oriented else ""
        if outcome.models:
            plates = len(outcome.gcode_files)
            return (
                f"done ({outcome.elapsed:.1f}s, {len(outcome.models)} models on "
                f"{plates} plate{'s' if plates != 1 else ''}{oriented})"
            )
        return f"done ({outcome.elapsed:.1f}s{oriented})"
    return f"FAILED: {outcome.message or 'unknown error'}"


def _report_batch(batch: BatchOutcome, root: Path, options: SliceOptions) -> None:
    """Summarise a batch: how many sliced, what printing them takes, and what failed."""
    total = batch.planned or len(batch.outcomes)
    if batch.interrupted:
        print("")
        running = ", ".join(str(model) for model in batch.interrupted_models) or "the batch"
        _error(
            f"Interrupted while slicing {running}; "
            f"{total - sum(outcome.model_count for outcome in batch.outcomes)} model file(s) "
            "were not sliced."
        )
    took = batch.wall_seconds or batch.elapsed
    print(
        f"Sliced {batch.models_succeeded} of {total} model file{'s' if total != 1 else ''} "
        f"in {_short_time(took)}."
    )
    grouped = [outcome for outcome in batch.succeeded if outcome.models]
    if grouped:
        on_plates = sum(len(outcome.models) for outcome in grouped)
        plates = sum(len(outcome.gcode_files) for outcome in grouped)
        print(f"  {on_plates} of them together on {plates} plate{'s' if plates != 1 else ''}.")
    oriented = sum(1 for outcome in batch.succeeded if outcome.auto_oriented)
    if oriented:
        print(f"  {oriented} of them with auto-orient.")
    totals = _describe_stats(batch.stats)
    if totals:
        print(f"  To print: {totals}")
    print(f"  Output: {batch.batch_directory}")
    try:
        report, _ = write_report(batch.outcomes, batch.batch_directory, root)
        print(f"  Report: {report}")
    except OSError as error:
        _error(f"  Could not write the report: {error}")
    if batch.failed:
        _error("  Failed:")
        for outcome in batch.failed:
            _error(f"    {outcome.model}: {outcome.message or 'unknown error'}")
        for hint in _hints(batch.failed, options):
            _error(f"  Hint: {hint}")


def _short_time(seconds: float) -> str:
    """Return a run's length: seconds with one decimal under a minute, else ``1h 2m 3s``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes}m {secs}s" if hours else f"{minutes}m {secs}s"


def _hints(failed: Sequence[SliceOutcome], options: SliceOptions) -> list[str]:
    """Return suggestions for failures that an option may fix."""
    hints = []
    for texts, applies, hint in _HINTS:
        count = sum(1 for outcome in failed if any(text in outcome.message for text in texts))
        if count and applies(options):
            hints.append(hint.format(count=count))
    return hints


def _describe_stats(stats: GcodeStats) -> str:
    """Return the print time and filament as one line, or "" if unknown."""
    parts = []
    if stats.print_seconds is not None:
        parts.append(format_duration(stats.print_seconds))
    if stats.filament_grams is not None:
        grams = stats.filament_grams
        parts.append(f"{grams / 1000:.2f} kg filament" if grams >= 1000 else f"{grams:.0f} g filament")
        used = stats.used_filaments()
        if len(used) > 1:
            each = " + ".join(f"{amount:.1f} g (slot {number})" for number, amount in used)
            changes = (
                f", {stats.filament_changes} filament changes" if stats.filament_changes else ""
            )
            parts[-1] += f" ({each}{changes})"
    if stats.filament_cost is not None and stats.filament_cost > 0:
        parts.append(f"filament cost {stats.filament_cost:.2f}")
    return ", ".join(parts)


def _report(outcome: SliceOutcome, options: SliceOptions) -> None:
    """Tell the user where the G-code is, or why slicing failed."""
    try:
        write_report([outcome], outcome.job_directory, outcome.model.parent)
    except OSError as error:
        logging.getLogger("batchslicer").warning("Could not write the report: %s", error)
    if outcome.success:
        oriented = " with auto-orient" if outcome.auto_oriented else ""
        copies = ""
        if outcome.copies > 1:
            plates = len(outcome.gcode_files)
            copies = f" ({outcome.copies} copies on {plates} plate{'s' if plates != 1 else ''})"
        print(f"Sliced {outcome.model.name}{copies}{oriented} in {outcome.elapsed:.1f}s:")
        for gcode in outcome.gcode_files:
            print(f"  {gcode}")
        totals = _describe_stats(outcome.stats)
        if totals:
            print(f"  To print: {totals}")
        return
    _error(f"Slicing {outcome.model.name} failed: {outcome.message or 'unknown error'}")
    _error(f"  Details: {outcome.job_directory}")
    for hint in _hints([outcome], options):
        _error(f"  Hint: {hint}")
