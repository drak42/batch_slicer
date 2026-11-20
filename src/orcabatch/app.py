"""Coordinate the OrcaBatch application lifecycle.

Startup shows the banner, configures logging, loads configuration, asks the
user which slicer to use, verifies the environment for that slicer, and asks
for the printer, filament and process presets where the slicer supports it.
The user then chooses one model file or a folder of models (subfolders
included) and an output folder, and the models are sliced into job folders.
Each step waits for the user's choice before the next begins.
"""

from pathlib import Path

from orcabatch.backends.orca import OrcaBackend
from orcabatch.backends.presets import PresetError, PresetLibrary
from orcabatch.backends.profiles import find_system_profiles
from orcabatch.backends.slicers import SLICERS, is_configured
from orcabatch.banner import get_banner
from orcabatch.cli.file_prompt import SliceInput, prompt_for_input
from orcabatch.cli.output_prompt import prompt_for_output
from orcabatch.cli.preset_prompt import prompt_for_presets
from orcabatch.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer
from orcabatch.core.config import get_config
from orcabatch.core.environment import EnvironmentService
from orcabatch.core.logging import configure_logging
from orcabatch.domain.presets import PresetSelection
from orcabatch.services.slicing import BatchOutcome, SliceOutcome, SlicingService


def main() -> int:
    """Start OrcaBatch and return a process exit status."""
    print(get_banner(), end="")
    logger = None

    try:
        logger = configure_logging()
        config = get_config()
        configured = [slicer for slicer in SLICERS if is_configured(slicer, config)]
        slicer = prompt_for_slicer(SLICERS, configured)
        logger.info("Selected slicer: %s", slicer.display_name)
        results = EnvironmentService(
            config=config,
            logger=logger,
            slicer=slicer,
        ).run_checks()

        failed = [result for result in results if not result.passed]
        if failed:
            logger.error("OrcaBatch startup failed environment verification.")
            print("OrcaBatch startup failed: environment verification failed.")
            for result in failed:
                print(f"  - {result.name}: {result.message}")
            return 1

        selection: PresetSelection | None = None
        library: PresetLibrary | None = None
        if slicer.supports_preset_selection:
            data_directory = Path(config.get(slicer.key, "datadir"))
            system_directory = find_system_profiles(
                Path(config.get(slicer.key, "executable")),
                data_directory,
                Path(config.get("paths", "data")) / "slicer-profiles",
                logger=logger,
            )
            library = PresetLibrary(
                data_directory,
                str(slicer.app_config_name),
                system_directory=system_directory,
                logger=logger,
            )
            selection = prompt_for_presets(library)
            logger.info(
                "Selected presets: printer=%s, filament=%s, process=%s",
                selection.printer.name,
                selection.filament.name,
                selection.process.name,
            )
        else:
            print(f"Preset selection is not available for {slicer.display_name} yet.")

        print(f"OrcaBatch ready. Slicer: {slicer.display_name}.")
        if selection is not None:
            print(f"  Printer:  {selection.printer.name}")
            print(f"  Filament: {selection.filament.name}")
            print(f"  Process:  {selection.process.name}")

        slice_input = prompt_for_input(Path(config.get("paths", "incoming")))
        output_directory = prompt_for_output(Path(config.get("paths", "output")))
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
    except (
        SlicerSelectionError,
        PresetError,
        FileNotFoundError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        print(f"OrcaBatch startup failed: {error}")
        if logger is not None:
            logger.error("OrcaBatch startup failed: %s", error)
        return 1

    if slice_input.is_folder:
        _report_batch(batch)
        return 0 if not batch.failed else 1
    _report(outcome)
    return 0 if outcome.success else 1


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
