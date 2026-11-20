"""Tests for slicing one model into a job folder."""

from datetime import datetime
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from orcabatch.backends.orca import OrcaResult
from orcabatch.domain.presets import Preset, PresetKind, PresetSelection
from orcabatch.services.slicing import SlicingService


NOW = datetime(2026, 11, 20, 14, 45, 30)


def _backend(*, exit_code: int = 0, gcode: bool = True, error_string: str = "Success.") -> Mock:
    """Return a backend whose slice writes what a real slicer would."""
    backend = Mock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        if gcode:
            (job / "plate_1.gcode").write_text("G1")
        (job / "result.json").write_text(json.dumps({"error_string": error_string}))
        return OrcaResult(exit_code == 0, exit_code, "", "", 2.5, ())

    backend.slice.side_effect = slice_
    return backend


def _selection() -> PresetSelection:
    """Return a preset selection."""
    def preset(name: str, kind: PresetKind) -> Preset:
        return Preset(name, kind, Path(name), is_user=False)

    return PresetSelection(
        preset("K2", PresetKind.PRINTER),
        preset("PLA", PresetKind.FILAMENT),
        preset("Fine", PresetKind.PROCESS),
    )


def test_successful_slice_reports_gcode_in_a_new_job_folder(tmp_path: Path) -> None:
    """Each job gets its own folder named after the model and time."""
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    job = tmp_path / "output" / "cube-20261120-144530"
    assert outcome.success
    assert outcome.job_directory == job
    assert outcome.gcode_files == (job / "plate_1.gcode",)
    assert outcome.message == "Success."
    assert outcome.elapsed == 2.5


def test_jobs_in_the_same_second_do_not_share_a_folder(tmp_path: Path) -> None:
    """A second job with the same name and time gets a numbered folder."""
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    first = service.slice(tmp_path / "cube.stl", tmp_path / "output")
    second = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    assert first.job_directory != second.job_directory
    assert second.job_directory.name == "cube-20261120-144530-2"


def test_presets_are_written_into_the_job_and_passed_to_the_slicer(tmp_path: Path) -> None:
    """The resolved presets are stored with the job and loaded by the slicer."""
    backend = _backend()
    library = Mock()
    settings = [tmp_path / "machine.json", tmp_path / "process.json"]
    filaments = [tmp_path / "filament.json"]
    library.write_resolved.return_value = (settings, filaments)
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW)
    selection = _selection()

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output", selection)

    library.write_resolved.assert_called_once_with(selection, outcome.job_directory / "presets")
    assert backend.slice.call_args.kwargs == {
        "load_settings": settings,
        "load_filaments": filaments,
    }


def test_slicing_with_presets_needs_a_library(tmp_path: Path) -> None:
    """Presets cannot be used without the library that resolves them."""
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    with pytest.raises(ValueError):
        service.slice(tmp_path / "cube.stl", tmp_path / "output", _selection())


def test_failure_uses_the_slicers_own_message(tmp_path: Path) -> None:
    """A failed slice reports the error_string the slicer wrote."""
    service = SlicingService(
        _backend(exit_code=250, gcode=False, error_string="The input model file can not be parsed."),
        logger=Mock(),
        clock=lambda: NOW,
    )

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    assert not outcome.success
    assert outcome.message == "The input model file can not be parsed."


def test_success_without_gcode_is_a_failure(tmp_path: Path) -> None:
    """A slicer that exits cleanly but writes no G-code has not succeeded."""
    service = SlicingService(_backend(gcode=False), logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    assert not outcome.success
    assert outcome.message == "The slicer finished but wrote no G-code."


def test_missing_result_file_falls_back_to_stderr(tmp_path: Path) -> None:
    """Without result.json, the last line of the slicer's error output is used."""
    backend = Mock()
    backend.slice.return_value = OrcaResult(False, -1, "", "starting\nOrcaSlicer timed out.", 9.0, ())
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    assert outcome.message == "OrcaSlicer timed out."


def test_batch_mirrors_source_folders_and_writes_presets_once(tmp_path: Path) -> None:
    """Each model gets a folder at its relative path; presets are shared by the batch."""
    source = tmp_path / "models"
    models = [source / "a.stl", source / "sub" / "deep" / "b.stl"]
    library = Mock()
    library.write_resolved.return_value = ([tmp_path / "m.json", tmp_path / "p.json"], [tmp_path / "f.json"])
    service = SlicingService(_backend(), presets=library, logger=Mock(), clock=lambda: NOW)
    started: list[tuple[int, int, str]] = []
    finished: list[bool] = []

    batch = service.slice_batch(
        models,
        source,
        tmp_path / "output",
        _selection(),
        on_start=lambda number, total, model: started.append((number, total, model.name)),
        on_result=lambda number, total, outcome: finished.append(outcome.success),
    )

    root = tmp_path / "output" / "models-20261120-144530"
    assert batch.batch_directory == root
    assert [outcome.job_directory for outcome in batch.outcomes] == [
        root / "a",
        root / "sub" / "deep" / "b",
    ]
    assert (root / "sub" / "deep" / "b" / "plate_1.gcode").is_file()
    library.write_resolved.assert_called_once_with(_selection(), root / "presets")
    assert started == [(1, 2, "a.stl"), (2, 2, "b.stl")]
    assert finished == [True, True]
    assert batch.elapsed == 5.0


def test_batch_continues_after_a_failure(tmp_path: Path) -> None:
    """One failed model does not stop the rest, and failures are reported."""
    source = tmp_path / "models"
    backend = Mock()
    results = iter([
        OrcaResult(False, 250, "", "bad model", 1.0, ()),
        OrcaResult(True, 0, "", "", 2.0, ()),
    ])

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        result = next(results)
        if result.success:
            (job / "plate_1.gcode").write_text("G1")
        return result

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch([source / "bad.stl", source / "good.stl"], source, tmp_path / "out")

    assert [outcome.model.name for outcome in batch.failed] == ["bad.stl"]
    assert [outcome.model.name for outcome in batch.succeeded] == ["good.stl"]
    assert batch.failed[0].message == "bad model"


def test_models_with_the_same_name_get_separate_folders(tmp_path: Path) -> None:
    """part.stl and part.3mf in one folder do not overwrite each other's results."""
    source = tmp_path / "models"
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch([source / "part.3mf", source / "part.stl"], source, tmp_path / "out")

    assert [outcome.job_directory.name for outcome in batch.outcomes] == ["part", "part-2"]
