"""Slice models with the chosen slicer and presets into job folders.

A single model gets a new folder under the output directory, named after the
model and the time, so earlier results are never overwritten. A batch gets one
such folder named after the source folder, inside which the source folder
structure is mirrored with one folder per model. When presets were chosen,
complete copies are written into the job (once per batch) so it records
exactly what was used. A failed model does not stop a batch. This module does
not prompt the user or choose presets.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path

from orcabatch.backends.orca import OrcaBackend, OrcaResult
from orcabatch.backends.presets import PresetLibrary
from orcabatch.core.logging import get_logger
from orcabatch.domain.presets import PresetSelection


_RESULT_FILE_NAME = "result.json"
_PRESETS_FOLDER_NAME = "presets"


@dataclass(frozen=True, slots=True)
class SliceOutcome:
    """Describe the result of slicing one model."""

    success: bool
    model: Path
    job_directory: Path
    gcode_files: tuple[Path, ...]
    message: str
    """The slicer's own explanation of the result, when it gives one."""

    elapsed: float


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """Describe the result of slicing every model in a batch."""

    batch_directory: Path
    outcomes: tuple[SliceOutcome, ...]

    @property
    def succeeded(self) -> tuple[SliceOutcome, ...]:
        """Return the outcomes of models that sliced successfully."""
        return tuple(outcome for outcome in self.outcomes if outcome.success)

    @property
    def failed(self) -> tuple[SliceOutcome, ...]:
        """Return the outcomes of models that failed."""
        return tuple(outcome for outcome in self.outcomes if not outcome.success)

    @property
    def elapsed(self) -> float:
        """Return the total slicing time in seconds."""
        return sum(outcome.elapsed for outcome in self.outcomes)


ProgressCallback = Callable[[int, int, Path], None]
"""Called as ``(number, total, model)`` before each model in a batch is sliced."""

ResultCallback = Callable[[int, int, SliceOutcome], None]
"""Called as ``(number, total, outcome)`` after each model in a batch is sliced."""


class SlicingService:
    """Run one slicing job for a model with the selected slicer and presets."""

    def __init__(
        self,
        backend: OrcaBackend,
        *,
        presets: PresetLibrary | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """Create a service that slices with ``backend``.

        ``presets`` is needed to slice with a preset selection.
        """
        self._backend = backend
        self._presets = presets
        self._logger = logger or get_logger()
        self._clock = clock

    def slice(
        self,
        model: Path,
        output_directory: Path,
        selection: PresetSelection | None = None,
    ) -> SliceOutcome:
        """Slice ``model`` into a new job folder inside ``output_directory``."""
        job_directory = self._create_unique_directory(
            output_directory / f"{model.stem}-{self._stamp()}"
        )
        settings, filaments = self._write_presets(selection, job_directory)
        return self._slice_into(model, job_directory, settings, filaments)

    def slice_batch(
        self,
        models: Sequence[Path],
        source_root: Path,
        output_directory: Path,
        selection: PresetSelection | None = None,
        *,
        on_start: ProgressCallback | None = None,
        on_result: ResultCallback | None = None,
    ) -> BatchOutcome:
        """Slice every model, mirroring their folders under ``source_root``.

        Results go into one new batch folder inside ``output_directory``, where
        ``source_root/a/b/part.stl`` is sliced into ``<batch>/a/b/part/``.
        Every model is attempted even if earlier ones fail.
        """
        batch_directory = self._create_unique_directory(
            output_directory / f"{source_root.name}-{self._stamp()}"
        )
        settings, filaments = self._write_presets(selection, batch_directory)
        self._logger.info(
            "Slicing %d model(s) from %s into %s", len(models), source_root, batch_directory
        )

        outcomes: list[SliceOutcome] = []
        total = len(models)
        for number, model in enumerate(models, start=1):
            if on_start is not None:
                on_start(number, total, model)
            relative_folder = model.parent.relative_to(source_root)
            job_directory = self._create_unique_directory(
                batch_directory / relative_folder / model.stem
            )
            outcome = self._slice_into(model, job_directory, settings, filaments)
            outcomes.append(outcome)
            if on_result is not None:
                on_result(number, total, outcome)

        batch = BatchOutcome(batch_directory=batch_directory, outcomes=tuple(outcomes))
        self._logger.info(
            "Batch finished: %d succeeded, %d failed.", len(batch.succeeded), len(batch.failed)
        )
        return batch

    def _slice_into(
        self,
        model: Path,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
    ) -> SliceOutcome:
        """Run the slicer for one model into an existing job folder."""
        self._logger.info("Slicing %s into %s", model, job_directory)
        result = self._backend.slice(
            model,
            job_directory,
            load_settings=settings,
            load_filaments=filaments,
        )
        return self._outcome(model, job_directory, result)

    def _write_presets(
        self,
        selection: PresetSelection | None,
        job_directory: Path,
    ) -> tuple[list[Path], list[Path]]:
        """Write complete preset files into the job, returning settings and filament files."""
        if selection is None:
            return [], []
        if self._presets is None:
            raise ValueError("A preset library is required to slice with presets.")
        settings, filaments = self._presets.write_resolved(
            selection, job_directory / _PRESETS_FOLDER_NAME
        )
        return list(settings), list(filaments)

    def _stamp(self) -> str:
        """Return the current time as used in job folder names."""
        return self._clock().strftime("%Y%m%d-%H%M%S")

    @staticmethod
    def _create_unique_directory(base: Path) -> Path:
        """Create ``base``, or ``base-2``, ``base-3``... if it exists, and return it."""
        directory = base
        counter = 2
        while directory.exists():
            directory = base.with_name(f"{base.name}-{counter}")
            counter += 1
        directory.mkdir(parents=True)
        return directory.absolute()

    def _outcome(self, model: Path, job_directory: Path, result: OrcaResult) -> SliceOutcome:
        """Combine the process result, result.json and the G-code files found."""
        gcode_files = tuple(sorted(job_directory.glob("*.gcode")))
        message = _read_result_message(job_directory / _RESULT_FILE_NAME)
        success = result.success and bool(gcode_files)
        if not message:
            message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
        if result.success and not gcode_files:
            message = "The slicer finished but wrote no G-code."
        if success:
            self._logger.info("Sliced %s into %d G-code file(s).", model, len(gcode_files))
        else:
            self._logger.error("Slicing %s failed: %s", model, message or "unknown error")
        return SliceOutcome(
            success=success,
            model=model,
            job_directory=job_directory,
            gcode_files=gcode_files,
            message=message,
            elapsed=result.elapsed,
        )


def _read_result_message(path: Path) -> str:
    """Return the slicer's ``error_string`` from result.json, or an empty string."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    message = data.get("error_string") if isinstance(data, dict) else None
    return message if isinstance(message, str) else ""
