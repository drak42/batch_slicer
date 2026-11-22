"""Slice models with the chosen slicer and presets into job folders.

A single model gets a new folder under the output directory, named after the
model and the time, so earlier results are never overwritten. A batch gets one
such folder named after the source folder, inside which the source folder
structure is mirrored with one folder per model. When presets were chosen,
complete copies are written into the job (once per batch) so it records
exactly what was used. A failed model does not stop a batch, and Ctrl+C stops
it cleanly, keeping the models already sliced. G-code files are
named after their model (``bracket.stl`` gives ``bracket.gcode``) instead of the
slicer's generic ``plate_N.gcode``.

With ``orient="retry"`` a model that fails is sliced once more with the
slicer's auto-orient; with ``"always"`` every model is. Several models can be
sliced at the same time (``jobs``), each by its own slicer process. The
slicer's own status files (``result.json``, ``NNNNN.log``) are read for the
outcome and then removed, so a job folder holds only G-code (and presets); a
failed model in a batch leaves no folder behind. This module does not prompt
the user or choose presets.
"""

import json
import logging
import re
import shutil
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from batchslicer.backends.orca import OrcaBackend, OrcaResult
from batchslicer.backends.presets import PresetLibrary
from batchslicer.core.logging import get_logger
from batchslicer.domain.options import MAX_JOBS, SliceOptions
from batchslicer.domain.presets import PresetSelection
from batchslicer.services.gcode_stats import GcodeStats, total_stats

_RESULT_FILE_NAME = "result.json"
_PRESETS_FOLDER_NAME = "presets"
_PLATE_GCODE_PATTERN = re.compile(r"plate_(\d+)\.gcode")
_VALIDATION_LOG_PATTERN = re.compile(r"\d+\.log")


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
    auto_oriented: bool = False
    """Whether the G-code came from slicing with the slicer's auto-orient."""

    stats: GcodeStats = field(default_factory=GcodeStats)
    """Print time and filament use, totalled over the G-code files."""


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """Describe the result of slicing every model in a batch."""

    batch_directory: Path
    outcomes: tuple[SliceOutcome, ...]
    """Finished models, in the order the models were given."""

    planned: int = 0
    """How many models the batch set out to slice."""

    interrupted: bool = False
    """Whether the batch was stopped (Ctrl+C) before every model was sliced."""

    interrupted_models: tuple[Path, ...] = ()
    """The models being sliced when the batch was interrupted."""

    wall_seconds: float = 0.0
    """How long the batch took from start to finish (less than :attr:`elapsed`
    when several models were sliced at once)."""

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
        """Return the total slicing time in seconds, summed over models."""
        return sum(outcome.elapsed for outcome in self.outcomes)

    @property
    def stats(self) -> GcodeStats:
        """Return the print time and filament of every successful model together."""
        total = GcodeStats()
        for outcome in self.succeeded:
            total = total + outcome.stats
        return total


ProgressCallback = Callable[[int, int, Path], None]
"""Called as ``(number, total, model)`` before each model in a batch is sliced."""

ResultCallback = Callable[[int, int, SliceOutcome], None]
"""Called as ``(finished, total, outcome)`` after each model in a batch is sliced,
from the calling thread, in the order models finish."""


class SlicingService:
    """Run one slicing job for a model with the selected slicer and presets."""

    def __init__(
        self,
        backend: OrcaBackend,
        *,
        presets: PresetLibrary | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] = datetime.now,
        options: SliceOptions | None = None,
    ) -> None:
        """Create a service that slices with ``backend``.

        ``presets`` is needed to slice with a preset selection; ``options``
        sets auto-orient and newer-file handling for every model.
        """
        self._backend = backend
        self._presets = presets
        self._logger = logger or get_logger()
        self._clock = clock
        self._options = options or SliceOptions()

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
        jobs: int = 1,
        on_start: ProgressCallback | None = None,
        on_result: ResultCallback | None = None,
    ) -> BatchOutcome:
        """Slice every model, mirroring their folders under ``source_root``.

        Results go into one new batch folder inside ``output_directory``, where
        ``source_root/a/b/part.stl`` is sliced into ``<batch>/a/b/part/``.
        Every model is attempted even if earlier ones fail. Up to ``jobs``
        models are sliced at the same time. If the batch is interrupted
        (Ctrl+C), running slicers are stopped and the models finished so far
        are returned.
        """
        if not 1 <= jobs <= MAX_JOBS:
            raise ValueError(f"jobs must be between 1 and {MAX_JOBS}: {jobs}")
        batch_directory = self._create_unique_directory(
            output_directory / f"{source_root.name}-{self._stamp()}"
        )
        settings, filaments = self._write_presets(selection, batch_directory)
        self._logger.info(
            "Slicing %d model(s) from %s into %s with %d job(s)",
            len(models),
            source_root,
            batch_directory,
            jobs,
        )

        started_at = time.perf_counter()
        total = len(models)
        finished: dict[int, SliceOutcome] = {}
        running: dict[Future[SliceOutcome], int] = {}
        job_directories: dict[int, Path] = {}
        queue = list(enumerate(models))
        interrupted = False
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="slice") as executor:
            try:
                while queue or running:
                    while queue and len(running) < jobs:
                        index, model = queue.pop(0)
                        if on_start is not None:
                            on_start(index + 1, total, model)
                        job_directory = self._create_unique_directory(
                            batch_directory / model.parent.relative_to(source_root) / model.stem
                        )
                        job_directories[index] = job_directory
                        future = executor.submit(
                            self._slice_into, model, job_directory, settings, filaments
                        )
                        running[future] = index
                    done, _ = wait(running, return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=running.__getitem__):
                        outcome = future.result()
                        index = running.pop(future)
                        finished[index] = outcome
                        if on_result is not None:
                            on_result(len(finished), total, outcome)
            except KeyboardInterrupt:
                interrupted = True
                self._backend.stop_all()
                for future in running:
                    future.cancel()
                self._logger.warning(
                    "Batch interrupted while slicing %s.",
                    ", ".join(str(models[index]) for index in sorted(running.values())),
                )

        if interrupted:
            for index in running.values():
                # Only partial output of this run is in an interrupted model's new folder.
                shutil.rmtree(job_directories[index], ignore_errors=True)
        _remove_empty_folders(batch_directory)

        batch = BatchOutcome(
            batch_directory=batch_directory,
            outcomes=tuple(finished[index] for index in sorted(finished)),
            planned=total,
            interrupted=interrupted,
            interrupted_models=tuple(models[index] for index in sorted(running.values()))
            if interrupted
            else (),
            wall_seconds=time.perf_counter() - started_at,
        )
        self._logger.info(
            "Batch %s: %d succeeded, %d failed, %d not sliced.",
            "interrupted" if batch.interrupted else "finished",
            len(batch.succeeded),
            len(batch.failed),
            total - len(batch.outcomes),
        )
        return batch

    def _slice_into(
        self,
        model: Path,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
    ) -> SliceOutcome:
        """Run the slicer for one model into an existing job folder.

        With orient "retry", a failure is retried once with auto-orient.
        """
        orient = self._options.orient
        self._logger.info("Slicing %s into %s", model, job_directory)
        result = self._run_slicer(model, job_directory, settings, filaments, orient == "always")
        outcome = self._outcome(model, job_directory, result, auto_oriented=orient == "always")
        if not outcome.success and orient == "retry" and result.exit_code != -1:
            self._logger.info("Retrying %s with auto-orient.", model)
            retry = self._run_slicer(model, job_directory, settings, filaments, True)
            retried = self._outcome(model, job_directory, retry, auto_oriented=True)
            if retried.success:
                outcome = replace(retried, elapsed=outcome.elapsed + retried.elapsed)
            else:
                outcome = replace(outcome, elapsed=outcome.elapsed + retried.elapsed)
        return outcome

    def _run_slicer(
        self,
        model: Path,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
        orient: bool,
    ) -> OrcaResult:
        """Run the slicer once for ``model``."""
        return self._backend.slice(
            model,
            job_directory,
            orient=orient,
            allow_newer_file=self._options.allow_newer_files,
            load_settings=settings,
            load_filaments=filaments,
        )

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
        link = not self._backend.resolves_inherits()
        settings, filaments = self._presets.write_resolved(
            selection, job_directory / _PRESETS_FOLDER_NAME, link_user_printer=link
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

    def _outcome(
        self,
        model: Path,
        job_directory: Path,
        result: OrcaResult,
        *,
        auto_oriented: bool = False,
    ) -> SliceOutcome:
        """Combine the process result, the slicer's status files and the G-code found.

        The status files are removed once read, so a retry starts clean and the
        job folder keeps only results.
        """
        gcode_files = _name_gcode_after_model(model, job_directory)
        message = _read_result_message(job_directory / _RESULT_FILE_NAME)
        success = result.success and bool(gcode_files)
        if not message:
            message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
        if result.success and not gcode_files:
            message = "The slicer finished but wrote no G-code."
        if not success:
            detail = _read_validation_log(job_directory)
            if detail and detail not in message:
                message = f"{message} ({detail})" if message else detail
        _remove_status_files(job_directory)
        if success:
            self._logger.info(
                "Sliced %s into %d G-code file(s)%s.",
                model,
                len(gcode_files),
                " with auto-orient" if auto_oriented else "",
            )
        else:
            self._logger.error("Slicing %s failed: %s", model, message or "unknown error")
        return SliceOutcome(
            success=success,
            model=model,
            job_directory=job_directory,
            gcode_files=gcode_files,
            message=message,
            elapsed=result.elapsed,
            auto_oriented=auto_oriented and success,
            stats=total_stats(gcode_files) if success else GcodeStats(),
        )


def _remove_status_files(job_directory: Path) -> None:
    """Remove the slicer's result.json and numbered validation logs from a job folder."""
    candidates = [job_directory / _RESULT_FILE_NAME, *job_directory.glob("[0-9]*.log")]
    for path in candidates:
        if path.name == _RESULT_FILE_NAME or _VALIDATION_LOG_PATTERN.fullmatch(path.name):
            path.unlink(missing_ok=True)


def _remove_empty_folders(root: Path) -> None:
    """Remove empty folders below ``root`` (deepest first), such as those of failed models."""
    folders = sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for folder in folders:
        try:
            folder.rmdir()
        except OSError:
            pass


def _read_validation_log(job_directory: Path) -> str:
    """Return the reason from a slicer's short validation log (``NNNNN.log``), if any.

    OrcaSlicer writes the specific reason a slice was rejected, such as "Too
    small line width", to a numbered log file next to result.json.
    """
    for path in sorted(job_directory.glob("[0-9]*.log")):
        try:
            if path.stat().st_size > 4096:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            line = text.splitlines()[0].strip()
            return line.removeprefix("got error when validate:").strip()
    return ""


def _read_result_message(path: Path) -> str:
    """Return the slicer's ``error_string`` from result.json, or an empty string."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    message = data.get("error_string") if isinstance(data, dict) else None
    return message if isinstance(message, str) else ""


def _name_gcode_after_model(model: Path, job_directory: Path) -> tuple[Path, ...]:
    """Rename the slicer's ``plate_N.gcode`` files after ``model`` and return all G-code.

    A single plate becomes ``<model name>.gcode``; several plates become
    ``<model name>_plate_N.gcode``. Other G-code files are left as they are.
    """
    plates = sorted(
        (
            (int(match.group(1)), path)
            for path in job_directory.glob("*.gcode")
            if (match := _PLATE_GCODE_PATTERN.fullmatch(path.name))
        ),
    )
    for number, path in plates:
        name = f"{model.stem}.gcode" if len(plates) == 1 else f"{model.stem}_plate_{number}.gcode"
        target = path.with_name(name)
        if target != path and not target.exists():
            path.rename(target)
    return tuple(sorted(job_directory.glob("*.gcode")))
