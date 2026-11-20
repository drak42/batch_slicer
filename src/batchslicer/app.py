"""Coordinate the BatchSlicer application lifecycle.

Startup configures logging, loads configuration, selects the slicer, verifies
the environment for it, and selects the printer, filament and process presets
where the slicer supports it. The models to slice (one file, or a folder and
its subfolders) and the output folder are then selected, and the models are
sliced into job folders. Each choice comes from the command line when given
there, and is otherwise asked for (unless ``--no-prompt`` is used).
"""

from collections.abc import Sequence
import logging
from pathlib import Path

from batchslicer.backends.orca import OrcaBackend
from batchslicer.backends.presets import PresetError, PresetLibrary
from batchslicer.backends.profiles import find_system_profiles
from batchslicer.backends.slicers import SLICERS, SlicerDefinition, get_slicer, is_configured
from batchslicer.banner import get_banner
from batchslicer.cli.arguments import RunOptions, parse_arguments
from batchslicer.cli.file_prompt import SliceInput, input_from_path, prompt_for_input
from batchslicer.cli.output_prompt import output_from_path, prompt_for_output
from batchslicer.cli.preset_prompt import find_preset, select_presets
from batchslicer.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer
from batchslicer.core.config import Config, get_config
from batchslicer.core.environment import EnvironmentService
from batchslicer.core.logging import configure_logging
from batchslicer.domain.presets import PresetKind, PresetSelection
from batchslicer.services.slicing import BatchOutcome, SliceOutcome, SlicingService


class _StartupFailed(Exception):
    """Raised when startup stops after its reason has already been shown."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run BatchSlicer with command-line ``argv`` and return a process exit status."""
    options = parse_arguments(argv)
    if not options.list_presets:
        print(get_banner(), end="")
    logger: logging.Logger | None = None

    try:
        logger = configure_logging()
        config = get_config()
        slicer = _select_slicer(options, config)
        logger.info("Selected slicer: %s", slicer.display_name)
        _verify_environment(config, logger, slicer)
        library = _preset_library(slicer, config, logger)

        if options.list_presets:
            _list_presets(slicer, library, options)
            return 0

        selection = _select_presets(options, slicer, library, logger)
        _show_ready(slicer, selection)
        slice_input = _select_input(options, config)
        output_directory = _select_output(options, config)
        logger.info(
            "Selected %d model(s) from %s; output to %s",
            len(slice_input.models),
            slice_input.root,
            output_directory,
        )
        backend = OrcaBackend(slicer=slicer, config=config, logger=logger)
        service = SlicingService(backend, presets=library, logger=logger)
        if slice_input.is_folder:
            batch = _slice_folder(service, slice_input, output_directory, selection)
        else:
            model = slice_input.models[0]
            print(f"Slicing {model.name} with {slicer.display_name}...")
            outcome = service.slice(model, output_directory, selection)
    except _StartupFailed:
        return 1
    except (
        SlicerSelectionError,
        PresetError,
        FileNotFoundError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        print(f"BatchSlicer startup failed: {error}")
        if logger is not None:
            logger.error("BatchSlicer startup failed: %s", error)
        return 1

    if slice_input.is_folder:
        _report_batch(batch)
        return 0 if not batch.failed else 1
    _report(outcome)
    return 0 if outcome.success else 1


def _select_slicer(options: RunOptions, config: Config) -> SlicerDefinition:
    """Return the slicer named on the command line, or ask for one."""
    configured = [slicer for slicer in SLICERS if is_configured(slicer, config)]
    if options.slicer is not None:
        slicer = get_slicer(options.slicer)
        if slicer not in configured:
            raise SlicerSelectionError(
                f"{slicer.display_name} is not configured. Set {slicer.key}.executable "
                f"and {slicer.key}.datadir in config/config.yaml."
            )
        return slicer
    if options.no_prompt:
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
        print("BatchSlicer startup failed: environment verification failed.")
        for result in failed:
            print(f"  - {result.name}: {result.message}")
        raise _StartupFailed


def _preset_library(
    slicer: SlicerDefinition,
    config: Config,
    logger: logging.Logger,
) -> PresetLibrary | None:
    """Return the slicer's preset library, or None if presets are not supported for it."""
    if not slicer.supports_preset_selection:
        return None
    data_directory = Path(config.get(slicer.key, "datadir"))
    system_directory = find_system_profiles(
        Path(config.get(slicer.key, "executable")),
        data_directory,
        Path(config.get("paths", "data")) / "slicer-profiles",
        logger=logger,
    )
    return PresetLibrary(
        data_directory,
        str(slicer.app_config_name),
        system_directory=system_directory,
        logger=logger,
    )


def _select_presets(
    options: RunOptions,
    slicer: SlicerDefinition,
    library: PresetLibrary | None,
    logger: logging.Logger,
) -> PresetSelection | None:
    """Return the presets named on the command line, asking for any not named."""
    named = [options.printer, options.filament, options.process]
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
        printer=options.printer,
        filament=options.filament,
        process=options.process,
        prompt=not options.no_prompt,
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
    options: RunOptions,
) -> None:
    """Print preset names usable with --printer, --filament and --process."""
    if library is None:
        raise SlicerSelectionError(
            f"Preset selection is not available for {slicer.display_name} yet."
        )
    if options.printer is None:
        print(f"Printers for {slicer.display_name} (use with --printer):")
        _print_names(library.printers())
        return
    printer = find_preset(PresetKind.PRINTER, library.printers(), options.printer)
    print(f"Filaments for {printer.name} (use with --filament):")
    _print_names(library.filaments_for(printer))
    print(f"Processes for {printer.name} (use with --process):")
    _print_names(library.processes_for(printer))


def _print_names(presets: Sequence[object]) -> None:
    """Print one preset name per line, marking the user's own presets."""
    for preset in presets:
        mine = "  (mine)" if getattr(preset, "is_user", False) else ""
        print(f"  {getattr(preset, 'name')}{mine}")


def _show_ready(slicer: SlicerDefinition, selection: PresetSelection | None) -> None:
    """Show the slicer and presets that will be used."""
    print(f"BatchSlicer ready. Slicer: {slicer.display_name}.")
    if selection is not None:
        print(f"  Printer:  {selection.printer.name}")
        print(f"  Filament: {selection.filament.name}")
        print(f"  Process:  {selection.process.name}")


def _select_input(options: RunOptions, config: Config) -> SliceInput:
    """Return the models given with --input, or ask what to slice."""
    if options.input is not None:
        return input_from_path(options.input)
    if options.no_prompt:
        raise SlicerSelectionError("--input is required when --no-prompt is used.")
    return prompt_for_input(Path(config.get("paths", "incoming")))


def _select_output(options: RunOptions, config: Config) -> Path:
    """Return the --output folder, the default folder without prompts, or ask."""
    if options.output is not None:
        return output_from_path(options.output)
    default = Path(config.get("paths", "output"))
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
    total = len(batch.outcomes)
    print(
        f"Sliced {len(batch.succeeded)} of {total} model file{'s' if total != 1 else ''} "
        f"in {batch.elapsed:.1f}s."
    )
    print(f"  Output: {batch.batch_directory}")
    if batch.failed:
        print("  Failed:")
        for outcome in batch.failed:
            print(f"    {outcome.model}: {outcome.message or 'unknown error'}")


def _report(outcome: SliceOutcome) -> None:
    """Tell the user where the G-code is, or why slicing failed."""
    if outcome.success:
        print(f"Sliced {outcome.model.name} in {outcome.elapsed:.1f}s:")
        for gcode in outcome.gcode_files:
            print(f"  {gcode}")
        return
    print(f"Slicing {outcome.model.name} failed: {outcome.message or 'unknown error'}")
    print(f"  Details: {outcome.job_directory}")
