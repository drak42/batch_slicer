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
slicer's auto-orient; with ``"always"`` every model is. With ``plates`` the
loose models (STL, OBJ, STEP) of each folder in a batch are sliced together:
the slicer arranges them, adding plates for any that do not fit, into a
``plates`` folder whose G-code is named after the source folder. If that
fails, the folder's models are sliced one by one to find the ones that fail,
and the rest are put back together on plates (parts that only slice after
an auto-orient retry keep their own plate). 3MF projects keep
their own plates. A single model (not a batch) can be sliced as several
copies (``copies``), which the slicer arranges, adding plates as needed. Several models can be
sliced at the same time (``jobs``), each by its own slicer process. The
slicer's own status files (``result.json``, ``NNNNN.log``) are read for the
outcome and then removed, so a job folder holds only G-code (and presets); a
failed model in a batch leaves no folder behind. Preview pictures are added
to the G-code (see :mod:`batchslicer.services.thumbnails`) unless turned off. This module does not prompt
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
from batchslicer.backends.projects import is_project, project_filaments
from batchslicer.core.logging import get_logger
from batchslicer.domain.options import MAX_JOBS, SliceOptions
from batchslicer.domain.presets import PresetSelection
from batchslicer.services.filament_matching import FilamentMatcher
from batchslicer.services.gcode_stats import GcodeStats, total_stats
from batchslicer.services.thumbnails import ThumbnailError, add_thumbnails

_RESULT_FILE_NAME = "result.json"
_PRESETS_FOLDER_NAME = "presets"
_PLATE_GCODE_PATTERN = re.compile(r"plate_(\d+)\.gcode")
_VALIDATION_LOG_PATTERN = re.compile(r"\d+\.log")
_PLATES_FOLDER_NAME = "plates"
_LOOSE_MODEL_SUFFIXES = frozenset({".stl", ".obj", ".step", ".stp"})
"""Model files that can share a plate (3MF projects bring their own plates)."""


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

    models: tuple[Path, ...] = ()
    """The model files sliced together on plates; empty for a single model
    (then :attr:`model` is the model, otherwise the folder they came from)."""

    copies: int = 1
    """How many copies of the model the G-code prints."""

    @property
    def model_count(self) -> int:
        """Return how many model files this outcome covers."""
        return len(self.models) or 1


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
    def models_succeeded(self) -> int:
        """Return how many model files sliced (a plate of several counts each)."""
        return sum(outcome.model_count for outcome in self.succeeded)

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
"""Called as ``(number, total, model)`` before each model in a batch is sliced
(``model`` is the folder when its models are sliced together on plates)."""

ResultCallback = Callable[[int, int, SliceOutcome], None]
"""Called as ``(finished, total, outcome)`` after each model (or plate group) in
a batch is sliced, from the calling thread, in the order they finish."""


@dataclass(frozen=True, slots=True)
class _Work:
    """One slicer job in a batch: a single model, or a folder's models together."""

    models: tuple[Path, ...]
    folder: Path | None = None
    """The folder whose models share plates; ``None`` for a single model."""

    @property
    def label(self) -> Path:
        return self.folder if self.folder is not None else self.models[0]


def _plan_work(models: Sequence[Path], plates: bool) -> list[_Work]:
    """Return the jobs for a batch, in model order.

    With ``plates``, the loose models of each folder (two or more) become one
    job, placed where the folder's first model was; everything else is sliced
    on its own.
    """
    groups: dict[Path, list[Path]] = {}
    if plates:
        for model in models:
            if model.suffix.casefold() in _LOOSE_MODEL_SUFFIXES:
                groups.setdefault(model.parent, []).append(model)
    work: list[_Work] = []
    for model in models:
        group = groups.get(model.parent)
        if group is not None and len(group) > 1 and model in group:
            if model == group[0]:
                work.append(_Work(tuple(group), model.parent))
            continue
        work.append(_Work((model,)))
    return work


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
        matcher: FilamentMatcher | None = None,
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
        self._matcher = matcher

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
        return self._slice_into(
            model, job_directory, settings, filaments, copies=self._options.copies
        )

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
        work = _plan_work(models, self._options.plates)
        total = len(work)
        finished: dict[int, tuple[SliceOutcome, ...]] = {}
        running: dict[Future[tuple[SliceOutcome, ...]], int] = {}
        job_directories: dict[int, list[Path]] = {}
        queue = list(enumerate(work))
        interrupted = False
        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="slice") as executor:
            try:
                while queue or running:
                    while queue and len(running) < jobs:
                        index, item = queue.pop(0)
                        if on_start is not None:
                            on_start(index + 1, total, item.label)
                        folder = batch_directory / item.models[0].parent.relative_to(source_root)
                        name = _PLATES_FOLDER_NAME if item.folder is not None else item.models[0].stem
                        job_directory = self._create_unique_directory(folder / name)
                        job_directories[index] = [job_directory]
                        if item.folder is None:
                            future = executor.submit(
                                self._slice_single, item.models[0], job_directory, settings, filaments
                            )
                        else:
                            future = executor.submit(
                                self._slice_together,
                                item,
                                job_directory,
                                settings,
                                filaments,
                                job_directories[index],
                            )
                        running[future] = index
                    done, _ = wait(running, return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=running.__getitem__):
                        outcomes = future.result()
                        index = running.pop(future)
                        finished[index] = outcomes
                        if on_result is not None:
                            for outcome in outcomes:
                                on_result(len(finished), total, outcome)
            except KeyboardInterrupt:
                interrupted = True
                self._backend.stop_all()
                for future in running:
                    future.cancel()
                self._logger.warning(
                    "Batch interrupted while slicing %s.",
                    ", ".join(str(work[index].label) for index in sorted(running.values())),
                )

        if interrupted:
            for index in running.values():
                # Only partial output of this run is in an interrupted model's new folders.
                for directory in job_directories[index]:
                    shutil.rmtree(directory, ignore_errors=True)
        _remove_empty_folders(batch_directory)

        batch = BatchOutcome(
            batch_directory=batch_directory,
            outcomes=tuple(
                outcome for index in sorted(finished) for outcome in finished[index]
            ),
            planned=len(models),
            interrupted=interrupted,
            interrupted_models=tuple(work[index].label for index in sorted(running.values()))
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

    def _slice_single(
        self,
        model: Path,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
    ) -> tuple[SliceOutcome, ...]:
        """Slice one model of a batch (see :meth:`_slice_into`)."""
        return (self._slice_into(model, job_directory, settings, filaments),)

    def _slice_together(
        self,
        work: _Work,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
        created: list[Path],
    ) -> tuple[SliceOutcome, ...]:
        """Slice a folder's models together on plates.

        If that fails, each model is sliced on its own to find the ones that
        fail, and those that slice as they are go back together on plates. The
        result lists the models left out (failed, or needing auto-orient)
        first and the plates last; if the models cannot go back together,
        the one-by-one results are returned. Folders made along the way are
        added to ``created`` so an interrupted batch can remove them.
        """
        assert work.folder is not None
        first = self._slice_models_together(work.folder, work.models, job_directory, settings, filaments)
        if first.success:
            return (first,)
        self._logger.info(
            "Slicing %s together failed (%s); slicing its models one by one.",
            work.folder,
            first.message or "unknown error",
        )
        shutil.rmtree(job_directory, ignore_errors=True)
        singles = []
        for model in work.models:
            directory = self._create_unique_directory(job_directory.parent / model.stem)
            created.append(directory)
            singles.append(self._slice_into(model, directory, settings, filaments))

        oriented = self._options.orient == "always"
        fit = [o for o in singles if o.success and o.auto_oriented == oriented]
        if len(fit) < 2 or len(fit) == len(work.models):
            return tuple(singles)
        regroup_directory = self._create_unique_directory(job_directory)
        created.append(regroup_directory)
        together = self._slice_models_together(
            work.folder, tuple(o.model for o in fit), regroup_directory, settings, filaments
        )
        if not together.success:
            self._logger.info(
                "The %d models of %s that slice on their own could not share plates either (%s).",
                len(fit),
                work.folder,
                together.message or "unknown error",
            )
            shutil.rmtree(regroup_directory, ignore_errors=True)
            return tuple(singles)
        for outcome in fit:
            shutil.rmtree(outcome.job_directory, ignore_errors=True)
        self._logger.info(
            "Put %d of the %d models of %s back together on plates.",
            len(fit),
            len(work.models),
            work.folder,
        )
        left_out = tuple(o for o in singles if o not in fit)
        elapsed = first.elapsed + together.elapsed + sum(o.elapsed for o in fit)
        return (*left_out, replace(together, elapsed=elapsed))

    def _slice_models_together(
        self,
        folder: Path,
        models: tuple[Path, ...],
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
    ) -> SliceOutcome:
        """Run the slicer once for ``models`` together, arranged on plates."""
        orient = self._options.orient == "always"
        self._logger.info(
            "Slicing %d models from %s together into %s", len(models), folder, job_directory
        )
        result = self._backend.slice(
            models,
            job_directory,
            orient=orient,
            arrange=True,
            allow_newer_file=self._options.allow_newer_files,
            load_settings=settings,
            load_filaments=filaments,
        )
        return self._outcome(folder, job_directory, result, auto_oriented=orient, models=models)

    def _slice_into(
        self,
        model: Path,
        job_directory: Path,
        settings: list[Path],
        filaments: list[Path],
        *,
        copies: int = 1,
    ) -> SliceOutcome:
        """Run the slicer for one model (``copies`` times over) into an existing job folder.

        With orient "retry", a failure is retried once with auto-orient. A 3MF
        project the slicer cannot apply presets to fails at once, with the reason.
        """
        slicer = self._backend.slicer
        if settings and not slicer.presets_in_projects and is_project(model):
            message = (
                f"{slicer.display_name} cannot use your presets for a 3MF project (its command "
                "line refuses them); slice it with OrcaSlicer or Bambu Studio, for example "
                "--slicer orca."
            )
            self._logger.warning("Not slicing %s: %s", model, message)
            return SliceOutcome(False, model, job_directory, (), message, 0.0)
        orient = self._options.orient
        self._logger.info(
            "Slicing %s%s into %s", model, f" ({copies} copies)" if copies > 1 else "", job_directory
        )
        result = self._run_slicer(
            model, job_directory, settings, filaments, orient == "always", copies
        )
        outcome = self._outcome(
            model, job_directory, result, auto_oriented=orient == "always", copies=copies
        )
        if not outcome.success and orient == "retry" and result.exit_code != -1:
            self._logger.info("Retrying %s with auto-orient.", model)
            retry = self._run_slicer(model, job_directory, settings, filaments, True, copies)
            retried = self._outcome(model, job_directory, retry, auto_oriented=True, copies=copies)
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
        copies: int = 1,
    ) -> OrcaResult:
        """Run the slicer once for ``model``."""
        return self._backend.slice(
            model,
            job_directory,
            orient=orient,
            copies=copies,
            allow_newer_file=self._options.allow_newer_files,
            load_settings=settings,
            load_filaments=self._filaments_for(model, job_directory, filaments),
        )

    def _filaments_for(self, model: Path, job_directory: Path, filaments: list[Path]) -> list[Path]:
        """Return one filament file per slot the model's project lists.

        With a matcher (``--loaded-filaments``), a multi-colour project's slots
        get the loaded filaments that match them. Otherwise the chosen
        filaments fill the slots in order, and as the slicer would keep the
        project's own filament for any slot it is not given, the last chosen
        filament fills the remaining slots.
        """
        if not filaments:
            return filaments
        if self._matcher is not None:
            matched = self._matcher.files_for(model, job_directory)
            if matched is not None:
                return matched
        slots = len(project_filaments(model))
        if slots <= len(filaments):
            return filaments
        self._logger.info(
            "%s lists %d filaments; using %s for slots %d-%d",
            model.name, slots, filaments[-1].name, len(filaments) + 1, slots,
        )
        return [*filaments, *[filaments[-1]] * (slots - len(filaments))]

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
        models: tuple[Path, ...] = (),
        copies: int = 1,
    ) -> SliceOutcome:
        """Combine the process result, the slicer's status files and the G-code found.

        ``model`` is the model, or the folder when ``models`` were sliced
        together (the G-code is then named after the folder). The status files
        are removed once read, so a retry starts clean and the job folder keeps
        only results.
        """
        gcode_files = _name_gcode_after(model.name if models else model.stem, job_directory)
        message = _read_result_message(job_directory / _RESULT_FILE_NAME)
        success = result.success and bool(gcode_files)
        if not message:
            message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
        if result.success and not gcode_files:
            message = "The slicer finished but wrote no G-code."
        if not success:
            detail = _read_validation_log(job_directory)
            # The log often repeats the slicer's message; add it only if it says more.
            if detail and detail not in message and not (message and message in detail):
                message = f"{message} ({detail})" if message else detail
        _remove_status_files(job_directory)
        if success and self._options.thumbnails:
            self._add_thumbnails(gcode_files)
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
            models=models,
            copies=copies,
        )


    def _add_thumbnails(self, gcode_files: Sequence[Path]) -> None:
        """Add preview pictures to each G-code file; a problem is logged, never a failure."""
        for gcode in gcode_files:
            try:
                result = add_thumbnails(gcode)
            except (ThumbnailError, ValueError) as error:
                self._logger.warning("No preview pictures for %s: %s", gcode, error)
                continue
            if result.added:
                sizes = ", ".join(f"{width}x{height}" for width, height in result.added)
                self._logger.info("Added preview pictures (%s) to %s", sizes, gcode)
            else:
                self._logger.info("No preview pictures for %s: %s", gcode, result.reason)


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


def _name_gcode_after(name: str, job_directory: Path) -> tuple[Path, ...]:
    """Rename the slicer's ``plate_N.gcode`` files after ``name`` and return all G-code.

    A single plate becomes ``<name>.gcode``; several plates become
    ``<name>_plate_N.gcode``. Other G-code files are left as they are.
    """
    plates = sorted(
        (
            (int(match.group(1)), path)
            for path in job_directory.glob("*.gcode")
            if (match := _PLATE_GCODE_PATTERN.fullmatch(path.name))
        ),
    )
    for number, path in plates:
        file_name = f"{name}.gcode" if len(plates) == 1 else f"{name}_plate_{number}.gcode"
        target = path.with_name(file_name)
        if target != path and not target.exists():
            path.rename(target)
    return tuple(sorted(job_directory.glob("*.gcode")))
