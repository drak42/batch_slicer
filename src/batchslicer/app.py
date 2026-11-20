"""Coordinate the BatchSlicer application lifecycle.

Startup configures logging, loads configuration, selects the slicer, verifies
the environment for it, and selects the printer, filament and process presets
where the slicer supports it. The models to slice (one file, or a folder and
its subfolders) and the output folder are then selected, and the models are
sliced into job folders. Each choice comes from the command line when given
there, and is otherwise asked for (unless ``--no-prompt`` is used).

Errors are reported on stderr. Ctrl+C stops cleanly with exit status 130 (a
batch keeps the models already sliced), and an unexpected error is reported in
one line with the full details written to the log. Exit statuses: 0 success,
1 failure, 2 invalid option (from argparse), 130 interrupted.
"""

import logging
import re
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from batchslicer.backends.orca import OrcaBackend
from batchslicer.backends.presets import PresetError, PresetLibrary
from batchslicer.backends.profiles import find_system_profiles
from batchslicer.backends.slicers import SLICERS, SlicerDefinition, get_slicer, is_configured
from batchslicer.banner import get_banner
from batchslicer.cli.arguments import RunOptions, parse_arguments
from batchslicer.cli.doctor import DoctorOptions, run_doctor
from batchslicer.cli.file_prompt import SliceInput, input_from_path, prompt_for_input
from batchslicer.cli.menu import confirm
from batchslicer.cli.output_prompt import output_from_path, prompt_for_output
from batchslicer.cli.preset_prompt import find_preset, select_presets
from batchslicer.cli.profile_prompt import prompt_for_profile
from batchslicer.cli.setup import SetupOptions, run_setup
from batchslicer.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer
from batchslicer.core.config import Config, find_config_file, get_config
from batchslicer.core.environment import EnvironmentService
from batchslicer.core.logging import configure_logging, current_log_file
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.domain.profiles import LAST_RUN, Profile, Target, combine, is_valid_name
from batchslicer.infrastructure.profiles import ProfileError, ProfileStore
from batchslicer.services.slicing import BatchOutcome, SliceOutcome, SlicingService

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INTERRUPTED = 130
"""The conventional status for a program stopped with Ctrl+C."""


class _StartupFailed(Exception):
    """Raised when startup stops after its reason has already been shown."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run BatchSlicer with command-line ``argv`` and return a process exit status."""
    options = parse_arguments(argv)
    try:
        if isinstance(options, SetupOptions):
            return _setup(options)
        if isinstance(options, DoctorOptions):
            return EXIT_SUCCESS if run_doctor(options) == 0 else EXIT_FAILURE
        return _run(options)
    except KeyboardInterrupt:
        _error("\nCancelled.")
        logging.getLogger("batchslicer").warning("Cancelled by the user.")
        return EXIT_INTERRUPTED
    except Exception as error:  # noqa: BLE001 - last-resort report for any bug
        return _report_unexpected(error)


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
        options, specs, offered_more = _plan_targets(options, profiles, logger)

        if options.list_presets:
            if len(specs) > 1:
                raise SlicerSelectionError("--list-presets works with one printer at a time.")
            spec = specs[0]
            slicer = _select_slicer(spec.slicer, options.no_prompt, config)
            _verify_environment(config, logger, slicer)
            _list_presets(slicer, _preset_library(slicer, config, logger), spec.printer)
            return EXIT_SUCCESS

        targets = _resolve_targets(specs, offered_more, options.no_prompt, config, logger)
        _show_ready(targets)
        slice_input = _select_input(options, config)
        output_directory = _select_output(options, config)
        logger.info(
            "Selected %d model(s) from %s; output to %s",
            len(slice_input.models),
            slice_input.root,
            output_directory,
        )
        _remember_choices(profiles, options, targets, slice_input, output_directory, logger)
        return _slice_targets(targets, slice_input, output_directory, config, logger)
    except _StartupFailed:
        return EXIT_FAILURE
    except (
        SlicerSelectionError,
        PresetError,
        ProfileError,
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

    def describe(self) -> str:
        """Return the slicer and presets as one line."""
        if self.selection is None:
            return self.slicer.display_name
        return (
            f"{self.slicer.display_name}: {self.selection.printer.name} / "
            f"{self.selection.filament.name} / {self.selection.process.name}"
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
        )


def _plan_targets(
    options: RunOptions,
    profiles: ProfileStore,
    logger: logging.Logger,
) -> tuple[RunOptions, list[Target], bool]:
    """Return the options with profile choices filled in, the targets to slice for,
    and whether to offer adding more printers.

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
        )

    if len(targets) > 1:
        if options.has_target_choices():
            raise SlicerSelectionError(
                "--slicer, --printer, --filament and --process describe one printer, so "
                "they cannot be combined with several printers. Save each printer as "
                "its own profile and list them with --profile."
            )
    else:
        base = targets[0]
        targets = [
            Target(
                slicer=options.slicer or base.slicer,
                printer=options.printer or base.printer,
                filament=options.filament or base.filament,
                process=options.process or base.process,
            )
        ]
    offer_more = interactive and not options.profiles and not options.has_target_choices()
    return options, targets, offer_more


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


def _remember_choices(
    profiles: ProfileStore,
    options: RunOptions,
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    output_directory: Path,
    logger: logging.Logger,
) -> None:
    """Save this run's choices as the last run, and as --save-profile if given."""
    choices = Profile(
        name=LAST_RUN,
        targets=tuple(target.as_target() for target in targets),
        input=slice_input.root if slice_input.is_folder else slice_input.models[0],
        output=output_directory,
    )
    try:
        profiles.save(choices)
    except ProfileError as error:
        logger.warning("Could not remember this run: %s", error)
    if options.save_profile is not None:
        profiles.save(replace(choices, name=options.save_profile))
        print(f"Saved these choices as profile '{options.save_profile}'.")
        logger.info("Saved profile %s", options.save_profile)


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
    logger.info(
        "Selected presets: printer=%s, filament=%s, process=%s",
        selection.printer.name,
        selection.filament.name,
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


def _show_ready(targets: list[_ResolvedTarget]) -> None:
    """Show the slicer(s) and presets that will be used."""
    if len(targets) > 1:
        print(f"BatchSlicer ready. Slicing for {len(targets)} printers:")
        for number, target in enumerate(targets, start=1):
            print(f"  {number}) {target.describe()}")
        return
    target = targets[0]
    print(f"BatchSlicer ready. Slicer: {target.slicer.display_name}.")
    if target.selection is not None:
        print(f"  Printer:  {target.selection.printer.name}")
        print(f"  Filament: {target.selection.filament.name}")
        print(f"  Process:  {target.selection.process.name}")


def _slice_targets(
    targets: list[_ResolvedTarget],
    slice_input: SliceInput,
    output_directory: Path,
    config: Config,
    logger: logging.Logger,
) -> int:
    """Slice the input for every target and return the run's exit status.

    With several targets, each one's results go into its own subfolder of the
    output folder, named after the printer.
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
        service = SlicingService(backend, presets=target.library, logger=logger)
        if slice_input.is_folder:
            batch = _slice_folder(service, slice_input, destination, target.selection)
            _report_batch(batch)
            if batch.interrupted:
                skipped = len(targets) - number
                if skipped:
                    _error(f"{skipped} more printer(s) were not started.")
                return EXIT_INTERRUPTED
            results.append((target, not batch.failed))
        else:
            model = slice_input.models[0]
            print(f"Slicing {model.name} with {target.slicer.display_name}...")
            outcome = service.slice(model, destination, target.selection)
            _report(outcome)
            results.append((target, outcome.success))

    if multi:
        succeeded = sum(1 for _, ok in results if ok)
        print("")
        print(f"Finished {len(results)} printers: {succeeded} without problems.")
        for target, ok in results:
            print(f"  {'ok    ' if ok else 'FAILED'} {target.describe()}")
    return EXIT_SUCCESS if all(ok for _, ok in results) else EXIT_FAILURE


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


def _select_input(options: RunOptions, config: Config) -> SliceInput:
    """Return the models given with --input, or ask what to slice."""
    if options.input is not None:
        return input_from_path(options.input)
    if options.no_prompt:
        raise SlicerSelectionError("--input is required when --no-prompt is used.")
    return prompt_for_input(config.get_path("paths", "incoming"))


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
) -> BatchOutcome:
    """Slice every model in the chosen folder, showing progress as it goes."""
    total = len(slice_input.models)
    print(f"Slicing {total} model file{'s' if total != 1 else ''} from {slice_input.root}...")

    def on_start(number: int, count: int, model: Path) -> None:
        print(f"  [{number}/{count}] {model.relative_to(slice_input.root)} ... ", end="", flush=True)

    def on_result(number: int, count: int, outcome: SliceOutcome) -> None:
        if outcome.success:
            print(f"done ({outcome.elapsed:.1f}s)")
        else:
            print(f"FAILED: {outcome.message or 'unknown error'}")

    return service.slice_batch(
        slice_input.models,
        slice_input.root,
        output_directory,
        selection,
        on_start=on_start,
        on_result=on_result,
    )


def _report_batch(batch: BatchOutcome) -> None:
    """Summarise a batch: how many sliced, where the results are, and what failed."""
    total = batch.planned or len(batch.outcomes)
    if batch.interrupted:
        print("")
        _error(
            f"Interrupted while slicing {batch.interrupted_model}; "
            f"{total - len(batch.outcomes) - 1} model file(s) were not started."
        )
    print(
        f"Sliced {len(batch.succeeded)} of {total} model file{'s' if total != 1 else ''} "
        f"in {batch.elapsed:.1f}s."
    )
    print(f"  Output: {batch.batch_directory}")
    if batch.failed:
        _error("  Failed:")
        for outcome in batch.failed:
            _error(f"    {outcome.model}: {outcome.message or 'unknown error'}")


def _report(outcome: SliceOutcome) -> None:
    """Tell the user where the G-code is, or why slicing failed."""
    if outcome.success:
        print(f"Sliced {outcome.model.name} in {outcome.elapsed:.1f}s:")
        for gcode in outcome.gcode_files:
            print(f"  {gcode}")
        return
    _error(f"Slicing {outcome.model.name} failed: {outcome.message or 'unknown error'}")
    _error(f"  Details: {outcome.job_directory}")
