"""Tests for slicing one model into a job folder."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.backends.orca import OrcaResult
from batchslicer.domain.options import SliceOptions
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.services.slicing import SliceOutcome, SlicingService

NOW = datetime(2026, 11, 20, 14, 45, 30)


def _backend(*, exit_code: int = 0, gcode: bool = True, error_string: str = "Success.") -> Mock:
    """Return a backend whose slice writes what a real slicer would."""
    backend = Mock()
    backend.resolves_inherits.return_value = False

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
    assert outcome.gcode_files == (job / "cube.gcode",)
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

    library.write_resolved.assert_called_once_with(
        selection, outcome.job_directory / "presets", link_user_printer=True
    )
    assert backend.slice.call_args.kwargs == {
        "orient": False,
        "copies": 1,
        "allow_newer_file": False,
        "load_settings": settings,
        "load_filaments": filaments,
    }


def test_a_multi_colour_project_gets_a_filament_for_every_slot(tmp_path: Path) -> None:
    """The last chosen filament fills the slots a 3MF project lists beyond those chosen."""
    import zipfile

    model = tmp_path / "bumper.3mf"
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps({"filament_colour": ["#000000", "#FFFFFF", "#FF0000"]}),
        )
    backend = _backend()
    library = Mock()
    filament = tmp_path / "filament.json"
    library.write_resolved.return_value = ([tmp_path / "machine.json"], [filament])
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW)

    service.slice(model, tmp_path / "output", _selection())
    service.slice(tmp_path / "cube.stl", tmp_path / "output", _selection())

    assert backend.slice.call_args_list[0].kwargs["load_filaments"] == [filament, filament, filament]
    assert backend.slice.call_args_list[1].kwargs["load_filaments"] == [filament]


def test_creality_print_projects_fail_at_once_with_the_reason(tmp_path: Path) -> None:
    """Creality Print refuses presets for 3MF projects, so it is not run for them."""
    import zipfile

    from batchslicer.backends.slicers import CREALITY_PRINT, ORCASLICER

    project = tmp_path / "bumper.3mf"
    with zipfile.ZipFile(project, "w") as archive:
        archive.writestr("Metadata/project_settings.config", "{}")
    library = Mock()
    library.write_resolved.return_value = ([tmp_path / "machine.json"], [tmp_path / "filament.json"])
    backend = _backend()
    backend.slicer = CREALITY_PRINT
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(project, tmp_path / "output", _selection())

    assert not outcome.success
    assert outcome.message.startswith("Creality Print cannot use your presets for a 3MF project")
    backend.slice.assert_not_called()
    assert service.slice(tmp_path / "cube.stl", tmp_path / "output", _selection()).success
    backend.slicer = ORCASLICER
    assert service.slice(project, tmp_path / "output", _selection()).success


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
    service = SlicingService(_backend(), presets=library, logger=Mock(), clock=lambda: NOW, options=SliceOptions(flat=False))
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
    assert (root / "sub" / "deep" / "b" / "b.gcode").is_file()
    library.write_resolved.assert_called_once_with(_selection(), root / "presets", link_user_printer=True)
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


def _backend_writing(*names: str) -> Mock:
    """Return a backend whose slice writes the given G-code file names."""
    backend = Mock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        for name in names:
            (job / name).write_text("G1")
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    return backend


def test_single_plate_gcode_is_named_after_the_model(tmp_path: Path) -> None:
    """bracket.stl is sliced to bracket.gcode, keeping the model's name."""
    service = SlicingService(_backend_writing("plate_1.gcode"), logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "Left Bracket v2.stl", tmp_path / "out")

    assert [path.name for path in outcome.gcode_files] == ["Left Bracket v2.gcode"]
    assert not (outcome.job_directory / "plate_1.gcode").exists()


def test_multiple_plates_keep_their_plate_numbers(tmp_path: Path) -> None:
    """A project with several plates gives one file per plate, named after the model."""
    service = SlicingService(
        _backend_writing("plate_1.gcode", "plate_2.gcode", "plate_10.gcode"),
        logger=Mock(),
        clock=lambda: NOW,
    )

    outcome = service.slice(tmp_path / "kit.3mf", tmp_path / "out")

    assert [path.name for path in outcome.gcode_files] == [
        "kit_plate_1.gcode",
        "kit_plate_10.gcode",
        "kit_plate_2.gcode",
    ]


def test_other_gcode_files_are_left_alone(tmp_path: Path) -> None:
    """Only the slicer's plate_N.gcode files are renamed."""
    service = SlicingService(
        _backend_writing("plate_1.gcode", "custom.gcode"), logger=Mock(), clock=lambda: NOW
    )

    outcome = service.slice(tmp_path / "part.stl", tmp_path / "out")

    assert [path.name for path in outcome.gcode_files] == ["custom.gcode", "part.gcode"]


def test_ctrl_c_stops_a_batch_and_keeps_finished_models(tmp_path: Path) -> None:
    """Interrupting a batch returns the models already sliced and names the one interrupted."""
    source = tmp_path / "models"
    backend = Mock()
    calls = iter([None, KeyboardInterrupt()])

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        step = next(calls)
        if isinstance(step, BaseException):
            raise step
        (job / "plate_1.gcode").write_text("G1")
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(flat=False))
    models = [source / "a.stl", source / "b.stl", source / "c.stl"]

    batch = service.slice_batch(models, source, tmp_path / "out")

    assert batch.interrupted
    assert batch.interrupted_models == (source / "b.stl",)
    assert batch.planned == 3
    assert [outcome.model.name for outcome in batch.succeeded] == ["a.stl"]
    assert (batch.batch_directory / "a" / "a.gcode").is_file()


def test_failure_includes_the_slicers_validation_log(tmp_path: Path) -> None:
    """OrcaSlicer's specific reason, written to NNNNN.log, is added to its generic message."""
    backend = Mock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        (job / "result.json").write_text(
            json.dumps({"error_string": "There are some incorrect slicing parameters."})
        )
        (job / "00000.log").write_text("got error when validate: Too small line width\n")
        return OrcaResult(False, 205, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(flat=False))

    outcome = service.slice(tmp_path / "part.stl", tmp_path / "out")

    assert outcome.message == (
        "There are some incorrect slicing parameters. (Too small line width)"
    )


_STATS = (
    "; filament used [mm] = 2485.84\n; filament used [g] = 7.41\n; total filament used [g] = 7.41\n"
    "; total filament cost = 0.15\n; estimated printing time (normal mode) = 1h 2m 10s\n"
)


def _orient_backend(*, fails_unless_oriented: bool = True) -> Mock:
    """Return a backend that only slices when auto-orient is on, as for a badly saved part."""
    backend = Mock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        ok = bool(kwargs["orient"]) or not fails_unless_oriented
        if ok:
            (job / "plate_1.gcode").write_text(_STATS)
            message = "Success."
        else:
            message = "Failed slicing the model."
            (job / "00000.log").write_text("found slicing or export error for partplate 1\n")
        (job / "result.json").write_text(json.dumps({"error_string": message}))
        return OrcaResult(ok, 0 if ok else 156, "", "", 2.0, ())

    backend.slice.side_effect = slice_
    return backend


def test_orient_retry_slices_a_failed_model_again_with_auto_orient(tmp_path: Path) -> None:
    """With orient "retry", a failure is retried with auto-orient and marked as such."""
    backend = _orient_backend()
    service = SlicingService(
        backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(orient="retry")
    )

    outcome = service.slice(tmp_path / "part.stl", tmp_path / "out")

    assert outcome.success
    assert outcome.auto_oriented
    assert outcome.elapsed == 4.0
    assert [call.kwargs["orient"] for call in backend.slice.call_args_list] == [False, True]
    assert sorted(path.name for path in outcome.job_directory.iterdir()) == ["part_1h2m.gcode"]


def test_orient_off_does_not_retry(tmp_path: Path) -> None:
    """By default a failed model is not sliced again."""
    backend = _orient_backend()
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "part.stl", tmp_path / "out")

    assert not outcome.success
    assert backend.slice.call_count == 1
    assert "partplate 1" in outcome.message


def test_orient_always_orients_every_model(tmp_path: Path) -> None:
    """With orient "always", the first and only attempt uses auto-orient."""
    backend = _orient_backend(fails_unless_oriented=False)
    service = SlicingService(
        backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(orient="always")
    )

    outcome = service.slice(tmp_path / "part.stl", tmp_path / "out")

    assert outcome.auto_oriented
    assert backend.slice.call_count == 1
    assert backend.slice.call_args.kwargs["orient"] is True


def test_allow_newer_files_is_passed_to_the_slicer(tmp_path: Path) -> None:
    """The newer-file option reaches the slicer command."""
    backend = _backend()
    service = SlicingService(
        backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(allow_newer_files=True)
    )

    service.slice(tmp_path / "part.3mf", tmp_path / "out")

    assert backend.slice.call_args.kwargs["allow_newer_file"] is True


def test_slicer_status_files_are_removed_and_failed_batch_folders_too(tmp_path: Path) -> None:
    """result.json and NNNNN.log are read, then removed; a failed model leaves no folder."""
    source = tmp_path / "models"
    service = SlicingService(_orient_backend(), logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch([source / "bad.stl"], source, tmp_path / "out")

    assert batch.failed[0].message.endswith("(found slicing or export error for partplate 1)")
    assert not (batch.batch_directory / "bad").exists()


def test_outcome_carries_print_time_and_filament(tmp_path: Path) -> None:
    """Statistics are read from the G-code and totalled for the batch."""
    source = tmp_path / "models"
    service = SlicingService(
        _orient_backend(fails_unless_oriented=False), logger=Mock(), clock=lambda: NOW
    )

    batch = service.slice_batch([source / "a.stl", source / "b.stl"], source, tmp_path / "out")

    assert batch.outcomes[0].stats.print_seconds == 3730
    assert batch.stats.filament_grams == pytest.approx(14.82)


def test_several_jobs_run_at_the_same_time_and_keep_model_order(tmp_path: Path) -> None:
    """With jobs=3, three slicers run at once; outcomes stay in model order."""
    source = tmp_path / "models"
    backend = Mock()
    lock = threading.Lock()
    active = 0
    most = 0
    another_reported = threading.Event()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        time.sleep(0.05)
        if model.stem == "a":
            # "a" finishes only after another model's result is reported, however
            # busy the machine is (with a time limit, should that never happen).
            another_reported.wait(timeout=10)
        (job / "plate_1.gcode").write_text("G1")
        with lock:
            active -= 1
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)
    models = [source / f"{name}.stl" for name in "abcdef"]
    finished: list[str] = []

    def on_result(number: int, total: int, outcome: SliceOutcome) -> None:
        finished.append(outcome.model.stem)
        another_reported.set()

    batch = service.slice_batch(models, source, tmp_path / "out", jobs=3, on_result=on_result)

    assert most == 3
    assert [outcome.model.stem for outcome in batch.outcomes] == list("abcdef")
    assert finished[0] != "a"
    assert len(batch.succeeded) == 6


def test_ctrl_c_with_several_jobs_stops_running_slicers(tmp_path: Path) -> None:
    """Interrupting a parallel batch stops the slicers and names the unfinished models."""
    source = tmp_path / "models"
    backend = Mock()
    calls = iter([None, None, KeyboardInterrupt()])
    lock = threading.Lock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        with lock:
            step = next(calls, None)
        if isinstance(step, BaseException):
            raise step
        (job / "plate_1.gcode").write_text("G1")
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)
    models = [source / f"{name}.stl" for name in "abcde"]

    batch = service.slice_batch(models, source, tmp_path / "out", jobs=2)

    assert batch.interrupted
    backend.stop_all.assert_called_once()
    assert source / "c.stl" in batch.interrupted_models
    assert len(batch.outcomes) + len(batch.interrupted_models) <= 5


def test_jobs_must_be_in_range(tmp_path: Path) -> None:
    """A batch needs at least one job."""
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    with pytest.raises(ValueError, match="jobs"):
        service.slice_batch([], tmp_path, tmp_path / "out", jobs=0)


def test_batch_records_its_wall_clock_time(tmp_path: Path) -> None:
    """The batch's own duration is kept apart from the summed slicer times."""
    source = tmp_path / "models"
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch([source / "a.stl", source / "b.stl"], source, tmp_path / "out", jobs=2)

    assert batch.elapsed == 5.0
    assert 0 < batch.wall_seconds < 5.0


def test_folders_left_empty_by_failures_are_removed(tmp_path: Path) -> None:
    """A source folder whose models all failed leaves no empty folders in the batch."""
    source = tmp_path / "models"
    service = SlicingService(_orient_backend(), logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch(
        [source / "kit" / "parts" / "bad.stl"], source, tmp_path / "out"
    )

    assert not (batch.batch_directory / "kit").exists()
    assert batch.batch_directory.is_dir()


def test_interrupted_models_leave_no_partial_output(tmp_path: Path) -> None:
    """The folder of a model being sliced when Ctrl+C came is removed with its partial files."""
    source = tmp_path / "models"
    backend = Mock()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        (job / "plate_1.gcode.tmp").write_text("G1")
        raise KeyboardInterrupt

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch([source / "a.stl"], source, tmp_path / "out")

    assert batch.interrupted_models == (source / "a.stl",)
    assert list(batch.batch_directory.iterdir()) == []


def test_user_printers_are_not_linked_for_slicers_that_resolve_inherits(tmp_path: Path) -> None:
    """For OrcaSlicer 2.5+, which looks up "inherits" itself, the link is left out."""
    backend = _backend()
    backend.resolves_inherits.return_value = True
    library = Mock()
    library.write_resolved.return_value = ([tmp_path / "m.json"], [tmp_path / "f.json"])
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW)

    service.slice(tmp_path / "cube.stl", tmp_path / "output", _selection())

    assert library.write_resolved.call_args.kwargs == {"link_user_printer": False}


def test_validation_log_that_repeats_the_message_is_not_added_again(tmp_path: Path) -> None:
    """OrcaSlicer 2.5's log often repeats its message; the reason is then given once."""
    backend = Mock()
    reason = "part.stl: One object has an empty first layer and can't be printed."

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        (job / "result.json").write_text(json.dumps({"error_string": reason}))
        (job / "00000.log").write_text(f"found slicing or export error for partplate 1: {reason}\n")
        return OrcaResult(False, 156, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW)

    assert service.slice(tmp_path / "part.stl", tmp_path / "out").message == reason


_TOOLPATHS = "; HEADER_BLOCK_END\nM83\n;TYPE:Outer wall\nG1 Z.2\nG1 X10 Y0 E1\nG1 X10 Y10 E1\nG1 X0 Y10 E1\n"


@pytest.mark.parametrize("thumbnails", [True, False])
def test_preview_pictures_are_added_unless_turned_off(tmp_path: Path, thumbnails: bool) -> None:
    """Sliced G-code gets preview pictures by default; --no-thumbnails leaves it as the slicer wrote it."""
    backend = _backend()

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        (job / "plate_1.gcode").write_text(_TOOLPATHS)
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    service = SlicingService(
        backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(thumbnails=thumbnails)
    )

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    text = outcome.gcode_files[0].read_text()
    assert ("; thumbnail begin 300x300" in text) is thumbnails
    assert ("; thumbnail begin 96x96" in text) is thumbnails


def test_a_picture_problem_does_not_fail_the_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If pictures cannot be added, the model still counts as sliced and the reason is logged."""
    from batchslicer.services import slicing
    from batchslicer.services.thumbnails import ThumbnailError

    monkeypatch.setattr(slicing, "add_thumbnails", Mock(side_effect=ThumbnailError("disk full")))
    logger = Mock()
    service = SlicingService(_backend(), logger=logger, clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output")

    assert outcome.success
    assert "disk full" in str(logger.warning.call_args)


def _plates_backend(*, together_fails: bool = False) -> Mock:
    """Return a backend that writes plates for several models, or fails for them."""
    backend = Mock()
    backend.resolves_inherits.return_value = False

    def slice_(model: object, job: Path, **kwargs: object) -> OrcaResult:
        if isinstance(model, tuple):
            if together_fails:
                (job / "result.json").write_text(json.dumps({"error_string": "bad part"}))
                return OrcaResult(False, 1, "", "", 3.0, ())
            assert kwargs["arrange"] is True
            (job / "plate_1.gcode").write_text("G1")
            (job / "plate_2.gcode").write_text("G1")
            return OrcaResult(True, 0, "", "", 5.0, ())
        (job / "plate_1.gcode").write_text("G1")
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    return backend


def test_plates_put_each_folders_loose_models_together(tmp_path: Path) -> None:
    """A folder's STL/OBJ files share plates; 3MF projects and lone models are sliced alone."""
    source = tmp_path / "models"
    kit = [source / "kit" / "a.stl", source / "kit" / "b.obj"]
    models = [source / "project.3mf", kit[0], source / "lone" / "c.stl", kit[1]]
    backend = _plates_backend()
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(plates=True, flat=False))
    started: list[Path] = []

    batch = service.slice_batch(models, source, tmp_path / "out", on_start=lambda n, t, m: started.append(m))

    assert started == [source / "project.3mf", source / "kit", source / "lone" / "c.stl"]
    together = batch.outcomes[1]
    assert together.model == source / "kit"
    assert together.models == tuple(kit)
    assert [path.relative_to(batch.batch_directory).as_posix() for path in together.gcode_files] == [
        "kit/plates/kit_plate_1.gcode",
        "kit/plates/kit_plate_2.gcode",
    ]
    assert (batch.planned, batch.models_succeeded, together.model_count) == (4, 4, 2)
    assert backend.slice.call_args_list[1].args[0] == tuple(kit)


def test_plates_fall_back_to_one_by_one(tmp_path: Path) -> None:
    """If the models cannot be sliced together, each is sliced on its own instead."""
    source = tmp_path / "models"
    kit = [source / "kit" / "a.stl", source / "kit" / "b.stl"]
    service = SlicingService(
        _plates_backend(together_fails=True), logger=Mock(), clock=lambda: NOW, options=SliceOptions(plates=True, flat=False)
    )

    batch = service.slice_batch(kit, source, tmp_path / "out")

    assert [outcome.model for outcome in batch.outcomes] == kit
    assert all(outcome.success and not outcome.models for outcome in batch.outcomes)
    assert not (batch.batch_directory / "kit" / "plates").exists()
    assert (batch.batch_directory / "kit" / "a" / "a.gcode").is_file()


def test_plates_are_off_by_default(tmp_path: Path) -> None:
    """Without the option every model is sliced on its own, as before."""
    source = tmp_path / "models"
    kit = [source / "kit" / "a.stl", source / "kit" / "b.stl"]
    service = SlicingService(_plates_backend(), logger=Mock(), clock=lambda: NOW)

    batch = service.slice_batch(kit, source, tmp_path / "out")

    assert [outcome.models for outcome in batch.outcomes] == [(), ()]


def test_interrupted_plates_leave_no_partial_output(tmp_path: Path) -> None:
    """Ctrl+C while a folder is sliced together removes its plates folder."""
    source = tmp_path / "models"
    backend = Mock()

    def slice_(model: object, job: Path, **kwargs: object) -> OrcaResult:
        (job / "plate_1.gcode.tmp").write_text("G1")
        raise KeyboardInterrupt

    backend.slice.side_effect = slice_
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(plates=True))

    batch = service.slice_batch([source / "a.stl", source / "b.stl"], source, tmp_path / "out")

    assert batch.interrupted_models == (source,)
    assert list(batch.batch_directory.iterdir()) == []


def test_copies_apply_to_a_single_model_only(tmp_path: Path) -> None:
    """A single model is sliced as N copies; models in a batch are sliced once each."""
    backend = _backend()
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(copies=4))

    single = service.slice(tmp_path / "part.stl", tmp_path / "out")
    batch = service.slice_batch([tmp_path / "m" / "a.stl"], tmp_path / "m", tmp_path / "out")

    assert single.copies == 4
    assert backend.slice.call_args_list[0].kwargs["copies"] == 4
    assert backend.slice.call_args_list[1].kwargs["copies"] == 1
    assert batch.outcomes[0].copies == 1


def _picky_backend(*, bad: str = "bad.stl", needs_orient: str = "") -> Mock:
    """Return a backend where ``bad`` never slices and ``needs_orient`` slices only auto-oriented.

    Several models together fail if any of them would fail on its own.
    """
    backend = Mock()
    backend.resolves_inherits.return_value = False

    def slices(model: Path, orient: bool) -> bool:
        return model.name != bad and (model.name != needs_orient or orient)

    def slice_(model: object, job: Path, **kwargs: object) -> OrcaResult:
        models = model if isinstance(model, tuple) else (model,)
        if all(slices(m, bool(kwargs.get("orient"))) for m in models):
            (job / "plate_1.gcode").write_text("G1")
            return OrcaResult(True, 0, "", "", 1.0, ())
        failing = next(m for m in models if not slices(m, bool(kwargs.get("orient"))))
        (job / "result.json").write_text(json.dumps({"error_string": f"{failing.name}: empty first layer"}))
        return OrcaResult(False, 1, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    return backend


def test_good_parts_go_back_on_plates_when_one_fails(tmp_path: Path) -> None:
    """The failing part is reported on its own; the others still share plates."""
    source = tmp_path / "models"
    kit = [source / "kit" / name for name in ("a.stl", "bad.stl", "b.stl", "c.stl")]
    backend = _picky_backend()
    service = SlicingService(backend, logger=Mock(), clock=lambda: NOW, options=SliceOptions(plates=True, flat=False))

    batch = service.slice_batch(kit, source, tmp_path / "out")

    failed, together = batch.outcomes
    assert (failed.model, failed.success) == (kit[1], False)
    assert "bad.stl: empty first layer" in failed.message
    assert together.success and together.model == source / "kit"
    assert together.models == (kit[0], kit[2], kit[3])
    assert [p.relative_to(batch.batch_directory).as_posix() for p in together.gcode_files] == [
        "kit/plates/kit.gcode"
    ]
    assert together.elapsed == 1.0 + 1.0 + 3 * 1.0  # first try, regroup, the three on their own
    assert sorted(p.name for p in (batch.batch_directory / "kit").iterdir()) == ["plates"]
    assert (batch.models_succeeded, batch.planned) == (3, 4)


def test_parts_rescued_by_auto_orient_keep_their_own_plate(tmp_path: Path) -> None:
    """A part that only slices auto-oriented stays apart; the rest share plates."""
    source = tmp_path / "models"
    kit = [source / "kit" / name for name in ("a.stl", "tilted.stl", "b.stl")]
    service = SlicingService(
        _picky_backend(bad="", needs_orient="tilted.stl"),
        logger=Mock(),
        clock=lambda: NOW,
        options=SliceOptions(plates=True, orient="retry"),
    )

    batch = service.slice_batch(kit, source, tmp_path / "out")

    alone, together = batch.outcomes
    assert alone.model == kit[1] and alone.success and alone.auto_oriented
    assert together.models == (kit[0], kit[2])
    assert batch.models_succeeded == 3


def test_one_good_part_is_not_put_on_plates_alone(tmp_path: Path) -> None:
    """With only one part left that slices, the one-by-one results are kept."""
    source = tmp_path / "models"
    kit = [source / "kit" / "a.stl", source / "kit" / "bad.stl"]
    service = SlicingService(_picky_backend(), logger=Mock(), clock=lambda: NOW, options=SliceOptions(plates=True))

    batch = service.slice_batch(kit, source, tmp_path / "out")

    assert [(o.model, o.success, o.models) for o in batch.outcomes] == [
        (kit[0], True, ()),
        (kit[1], False, ()),
    ]


def test_flat_output_puts_all_gcode_in_the_batch_folder(tmp_path: Path) -> None:
    """--flat moves each G-code up; a name used twice gets its folders in front, then a number."""
    from batchslicer.domain.options import SliceOptions

    root = tmp_path / "in"
    models = [root / "a" / "arm.stl", root / "b" / "arm.stl", root / "arm.stl", root / "b" / "deep" / "rest.stl"]
    for model in models:
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("solid")
    service = SlicingService(_backend(), logger=Mock(), clock=lambda: NOW, options=SliceOptions(flat=True))

    batch = service.slice_batch(models, root, tmp_path / "out")

    folder = batch.batch_directory
    assert [outcome.gcode_files for outcome in batch.outcomes] == [
        (folder / "arm.gcode",), (folder / "b-arm.gcode",), (folder / "arm (2).gcode",), (folder / "rest.gcode",),
    ]
    assert sorted(path.name for path in folder.iterdir()) == ["arm (2).gcode", "arm.gcode", "b-arm.gcode", "rest.gcode"]


def _backend_writing_stats() -> Mock:
    """Return a backend whose G-code says its material and print time, as slicers write them."""
    backend = Mock()
    backend.resolves_inherits.return_value = False

    def slice_(model: Path, job: Path, **kwargs: object) -> OrcaResult:
        (job / "plate_1.gcode").write_text(
            "G1\n; estimated printing time (normal mode) = 2h 50m 53s\n; filament_type = PETG\n"
        )
        return OrcaResult(True, 0, "", "", 1.0, ())

    backend.slice.side_effect = slice_
    return backend


@pytest.mark.parametrize(("name_details", "expected"), [(True, "bracket_PETG_2h51m.gcode"), (False, "bracket.gcode")])
def test_gcode_name_gets_the_material_and_print_time(tmp_path: Path, name_details: bool, expected: str) -> None:
    """By default the G-code is named bracket_PETG_2h51m.gcode; --no-name-details keeps bracket.gcode."""
    from batchslicer.domain.options import SliceOptions

    model = tmp_path / "bracket.stl"
    model.write_text("solid")
    service = SlicingService(
        _backend_writing_stats(), logger=Mock(), clock=lambda: NOW,
        options=SliceOptions(thumbnails=False, name_details=name_details),
    )

    outcome = service.slice(model, tmp_path / "out")

    assert [path.name for path in outcome.gcode_files] == [expected]
    assert outcome.gcode_files[0].is_file()


def _library_writing_presets(directory: Path) -> Mock:
    """Return a preset library mock whose write_resolved writes real preset files."""
    library = Mock()

    def write_resolved(selection: PresetSelection, presets: Path, **kwargs: object) -> tuple[list[Path], list[Path]]:
        presets.mkdir(parents=True, exist_ok=True)
        files = []
        for name, data in (
            ("machine", {"type": "machine", "printer_settings_id": "K2", "nozzle_diameter": ["0.4"]}),
            ("process", {"type": "process", "print_settings_id": "Fine", "layer_height": "0.12"}),
            ("filament", {"type": "filament", "filament_settings_id": ["PLA"], "filament_type": ["PLA"]}),
        ):
            path = presets / f"{name}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            files.append(path)
        return files[:2], files[2:]

    library.write_resolved.side_effect = write_resolved
    library.changed_settings.return_value = ("0.20mm Standard", [("layer_height", "0.2", "0.12")])
    return library


def test_a_print_settings_summary_is_written_with_the_presets(tmp_path: Path) -> None:
    """The job folder gets print-settings.txt naming the presets and the user's changes."""
    library = _library_writing_presets(tmp_path)
    backend = _backend()
    backend.slicer.display_name = "Creality Print"
    selection = PresetSelection(
        Preset("K2", PresetKind.PRINTER, Path("K2"), is_user=False),
        Preset("PLA", PresetKind.FILAMENT, Path("PLA"), is_user=False),
        Preset("Fine", PresetKind.PROCESS, Path("Fine"), is_user=True),
    )
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output", selection)

    text = (outcome.job_directory / "print-settings.txt").read_text(encoding="utf-8")
    assert "with Creality Print" in text
    assert "Printer:  K2" in text
    assert "Process:  Fine" in text
    assert "layer_height: 0.2 -> 0.12" in text
    library.changed_settings.assert_called_once_with(selection.process)  # shipped presets are skipped


def test_a_summary_that_cannot_be_written_does_not_stop_the_slice(tmp_path: Path) -> None:
    """If the preset files cannot be read, a warning is logged and slicing goes on."""
    library = Mock()
    library.write_resolved.return_value = ([tmp_path / "missing.json"], [])
    logger = Mock()
    service = SlicingService(_backend(), presets=library, logger=logger, clock=lambda: NOW)

    outcome = service.slice(tmp_path / "cube.stl", tmp_path / "output", _selection())

    assert outcome.success
    assert not (outcome.job_directory / "print-settings.txt").exists()
    assert any("print settings summary" in str(call) for call in logger.warning.call_args_list)
