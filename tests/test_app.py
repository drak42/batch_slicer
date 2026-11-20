"""Tests for the BatchSlicer application bootstrap."""

import logging
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer import app
from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, SLICERS
from batchslicer.cli.file_prompt import SliceInput
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.services.slicing import BatchOutcome, SliceOutcome


def _all_output(capsys: pytest.CaptureFixture[str]) -> str:
    """Return everything printed, normal output and errors together."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _single_input() -> SliceInput:
    """Return a one-file slicing input."""
    return SliceInput(root=Path("/models"), models=(Path("/models/cube.stl"),), is_folder=False)


def _outcome(
    *, success: bool, message: str = "Success.", model: str = "/models/cube.stl"
) -> SliceOutcome:
    """Return a slicing outcome for startup tests."""
    job = Path("/out/cube-20261120-120000")
    return SliceOutcome(
        success=success,
        model=Path(model),
        job_directory=job,
        gcode_files=(job / "plate_1.gcode",) if success else (),
        message=message,
        elapsed=1.25,
    )


@dataclass
class _Result:
    """Provide the environment result shape used by the application."""

    passed: bool
    name: str = "check"
    message: str = ""


@pytest.fixture
def startup_mocks(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock, Mock, Mock]:
    """Replace startup services with test doubles."""
    logger = Mock()
    configure_logging = Mock(return_value=logger)
    get_config = Mock(return_value=Mock())
    config = get_config.return_value
    config.get.return_value = "configured-path"
    config.get_path.side_effect = lambda section, key: Path(config.get(section, key))
    config.get_program.side_effect = lambda section, key="executable": Path(
        config.get(section, key)
    )
    config.path = Path("/settings/config.yaml")
    monkeypatch.setattr(app, "find_config_file", Mock(return_value=Path("/settings/config.yaml")))
    monkeypatch.setattr(app, "confirm", Mock(return_value=False))
    profile_store = Mock()
    profile_store.return_value.load.return_value = {}
    monkeypatch.setattr(app, "ProfileStore", profile_store)
    environment_service = Mock()
    environment_service.return_value.run_checks.return_value = [_Result(passed=True)]

    monkeypatch.setattr(app, "configure_logging", configure_logging)
    monkeypatch.setattr(app, "get_config", get_config)
    monkeypatch.setattr(app, "EnvironmentService", environment_service)
    monkeypatch.setattr(app, "is_configured", Mock(return_value=True))
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=BAMBU_STUDIO))
    monkeypatch.setattr(app, "prompt_for_input", Mock(return_value=_single_input()))
    monkeypatch.setattr(app, "prompt_for_output", Mock(return_value=Path("/out")))
    monkeypatch.setattr(app, "OrcaBackend", Mock())
    monkeypatch.setattr(app, "find_system_profiles", Mock(return_value=Path("/profiles")))
    slicing_service = Mock()
    slicing_service.return_value.slice.return_value = _outcome(success=True)
    monkeypatch.setattr(app, "SlicingService", slicing_service)
    return configure_logging, get_config, environment_service, logger


def test_successful_startup_returns_zero_and_reports_ready(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Successful startup displays the banner and readiness message."""
    result = app.main([])

    assert result == 0
    output = capsys.readouterr().out
    assert app.get_banner() in output
    assert "BatchSlicer ready. Slicer: Bambu Studio." in output


def test_environment_failure_returns_nonzero_without_ready_message(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failed environment checks prevent the application from becoming ready."""
    startup_mocks[2].return_value.run_checks.return_value = [_Result(passed=False)]

    result = app.main([])

    assert result != 0
    assert "BatchSlicer ready." not in capsys.readouterr().out


def test_configuration_failure_is_handled_cleanly(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expected configuration failures return a status without a traceback."""
    startup_mocks[1].side_effect = FileNotFoundError("missing config")

    result = app.main([])

    assert result != 0
    assert "BatchSlicer startup failed: missing config" in _all_output(capsys)


def test_startup_uses_services_in_order(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """Startup delegates configuration and environment work to existing services."""
    configure_logging, get_config, environment_service, logger = startup_mocks

    app.main([])

    app.find_config_file.assert_called_once_with(None)
    get_config.assert_called_once_with(Path("/settings/config.yaml"))
    configure_logging.assert_called_once_with(log_directory=Path("configured-path"))
    environment_service.assert_called_once_with(
        config=get_config.return_value,
        logger=logger,
        slicer=BAMBU_STUDIO,
    )
    environment_service.return_value.run_checks.assert_called_once_with()


def test_slicer_is_chosen_before_environment_checks(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user is prompted with every slicer, configured ones marked, before startup proceeds."""
    _, get_config, environment_service, _ = startup_mocks
    calls: list[str] = []
    monkeypatch.setattr(
        app,
        "is_configured",
        lambda slicer, config: slicer is BAMBU_STUDIO,
    )

    def prompt(slicers: object, configured: object) -> object:
        calls.append("prompt")
        assert slicers == SLICERS
        assert configured == [BAMBU_STUDIO]
        assert not environment_service.called
        return BAMBU_STUDIO

    monkeypatch.setattr(app, "prompt_for_slicer", prompt)

    assert app.main([]) == 0
    assert calls == ["prompt"]


def test_no_slicer_selected_stops_startup(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If no slicer is chosen, startup stops before verification."""
    environment_service = startup_mocks[2]
    monkeypatch.setattr(
        app,
        "prompt_for_slicer",
        Mock(side_effect=SlicerSelectionError("No slicer selected.")),
    )

    assert app.main([]) == 1
    assert not environment_service.called
    output = _all_output(capsys)
    assert "BatchSlicer startup failed: No slicer selected." in output
    assert "BatchSlicer ready." not in output


def test_environment_failure_lists_failed_checks(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each failed check is named so the user knows what to fix."""
    failed = Mock(passed=False, message="Bambu Studio executable not found: /x")
    failed.name = "slicer_executable"
    startup_mocks[2].return_value.run_checks.return_value = [failed]

    app.main([])

    assert "slicer_executable: Bambu Studio executable not found: /x" in _all_output(capsys)

def _selection() -> PresetSelection:
    """Return a preset selection for startup tests."""
    def preset(name: str, kind: PresetKind) -> Preset:
        return Preset(name=name, kind=kind, path=Path(name), is_user=False)

    return PresetSelection(
        printer=preset("K2 Plus", PresetKind.PRINTER),
        filament=preset("Generic PETG", PresetKind.FILAMENT),
        process=preset("0.12mm PETG", PresetKind.PROCESS),
    )


def test_presets_are_chosen_after_checks_for_supported_slicers(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """For Creality Print the user picks presets from its data directory before ready."""
    _, get_config, environment_service, _ = startup_mocks
    get_config.return_value.get.return_value = "/data/creality"
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    library = Mock()
    monkeypatch.setattr(app, "PresetLibrary", library)

    def prompt(source: object, **kwargs: object) -> PresetSelection:
        assert environment_service.return_value.run_checks.called
        assert source is library.return_value
        return _selection()

    monkeypatch.setattr(app, "select_presets", prompt)

    assert app.main([]) == 0
    get_config.return_value.get.assert_any_call("creality_print", "datadir")
    assert library.call_args.args == (Path("/data/creality"), "Creality.conf")
    assert library.call_args.kwargs["system_directory"] == Path("/profiles")
    assert app.find_system_profiles.call_args.args[1] == Path("/data/creality")
    output = capsys.readouterr().out
    assert "Printer:  K2 Plus" in output
    assert "Filament: Generic PETG" in output
    assert "Process:  0.12mm PETG" in output


def test_preset_selection_is_skipped_with_a_note_for_other_slicers(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Slicers without preset support say so and still start."""
    prompt = Mock()
    monkeypatch.setattr(app, "select_presets", prompt)

    assert app.main([]) == 0
    assert not prompt.called
    assert "Preset selection is not available for Bambu Studio yet." in capsys.readouterr().out


def test_cancelled_preset_selection_stops_startup(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Startup does not proceed without presets."""
    startup_mocks[1].return_value.get.return_value = "/data/creality"
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(
        app,
        "select_presets",
        Mock(side_effect=SlicerSelectionError("No filament selected.")),
    )

    assert app.main([]) == 1
    output = _all_output(capsys)
    assert "BatchSlicer startup failed: No filament selected." in output
    assert "BatchSlicer ready." not in output


def test_model_is_chosen_from_incoming_and_sliced_into_output(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After setup, the chosen model is sliced into the chosen output folder."""
    _, get_config, _, logger = startup_mocks
    paths = {
        ("paths", "incoming"): "incoming",
        ("paths", "output"): "output",
        ("paths", "logs"): "logs",
        ("paths", "profiles"): "profiles.yaml",
    }
    get_config.return_value.get.side_effect = lambda section, key: paths[(section, key)]

    assert app.main([]) == 0

    app.prompt_for_input.assert_called_once_with(Path("incoming"))
    app.prompt_for_output.assert_called_once_with(Path("output"))
    app.OrcaBackend.assert_called_once_with(
        slicer=BAMBU_STUDIO, config=get_config.return_value, logger=logger
    )
    app.SlicingService.return_value.slice.assert_called_once_with(
        Path("/models/cube.stl"), Path("/out"), None
    )
    output = capsys.readouterr().out
    assert "Sliced cube.stl in 1.2s:" in output
    assert "/out/cube-20261120-120000/plate_1.gcode" in output


def test_presets_and_library_are_used_for_slicing(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chosen presets and their library are passed to the slicing service."""
    startup_mocks[1].return_value.get.return_value = "/data/creality"
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    library = Mock()
    monkeypatch.setattr(app, "PresetLibrary", library)
    selection = _selection()
    monkeypatch.setattr(app, "select_presets", Mock(return_value=selection))

    app.main([])

    assert app.SlicingService.call_args.kwargs["presets"] is library.return_value
    assert app.SlicingService.return_value.slice.call_args.args[2] is selection


def test_failed_slice_reports_the_slicers_reason(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed slice exits non-zero and shows the slicer's own explanation."""
    app.SlicingService.return_value.slice.return_value = _outcome(
        success=False, message="The input model file to the slicer can not be parsed."
    )

    assert app.main([]) == 1
    output = _all_output(capsys)
    assert "Slicing cube.stl failed: The input model file to the slicer can not be parsed." in output
    assert "Details: /out/cube-20261120-120000" in output


def test_cancelled_model_choice_stops_before_slicing(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is sliced if no model is chosen."""
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(side_effect=SlicerSelectionError("No model file selected.")),
    )

    assert app.main([]) == 1
    assert not app.SlicingService.return_value.slice.called


def test_folder_is_sliced_as_a_batch_with_progress_and_summary(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A folder choice slices every model, reports progress, and summarises failures."""
    models = (Path("/models/a.stl"), Path("/models/sub/b.stl"))
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(return_value=SliceInput(root=Path("/models"), models=models, is_folder=True)),
    )
    good = _outcome(success=True, model="/models/a.stl")
    bad = _outcome(success=False, message="can not be parsed", model="/models/sub/b.stl")

    def slice_batch(models_arg, root, output, selection, *, on_start, on_result):
        for number, outcome in enumerate((good, bad), start=1):
            on_start(number, 2, outcome.model)
            on_result(number, 2, outcome)
        return BatchOutcome(batch_directory=Path("/out/models-20261120-120000"), outcomes=(good, bad))

    app.SlicingService.return_value.slice_batch.side_effect = slice_batch

    assert app.main([]) == 1

    call = app.SlicingService.return_value.slice_batch.call_args
    assert call.args[:3] == (models, Path("/models"), Path("/out"))
    output = _all_output(capsys)
    assert "Slicing 2 model files from /models..." in output
    assert "[1/2] a.stl ... done (1.2s)" in output
    assert "[2/2] sub/b.stl ... FAILED: can not be parsed" in output
    assert "Sliced 1 of 2 model files in 2.5s." in output
    assert "Output: /out/models-20261120-120000" in output
    assert "/models/sub/b.stl: can not be parsed" in output


def test_successful_batch_exits_zero(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch where every model sliced exits with status 0."""
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(return_value=SliceInput(Path("/models"), (Path("/models/a.stl"),), True)),
    )
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(
        Path("/out/b"), (_outcome(success=True),)
    )

    assert app.main([]) == 0


def _no_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every interactive prompt fail the test if it is used."""
    for name in ("prompt_for_slicer", "prompt_for_input", "prompt_for_output"):
        monkeypatch.setattr(app, name, Mock(side_effect=AssertionError(f"{name} was called")))


def test_command_line_run_needs_no_prompts(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With every choice on the command line, nothing is asked and slicing runs."""
    _no_prompts(monkeypatch)
    library = Mock()
    monkeypatch.setattr(app, "PresetLibrary", library)
    select_presets = Mock(return_value=_selection())
    monkeypatch.setattr(app, "select_presets", select_presets)
    single = _single_input()
    input_from_path = Mock(return_value=single)
    output_from_path = Mock(return_value=Path("/out/k2"))
    monkeypatch.setattr(app, "input_from_path", input_from_path)
    monkeypatch.setattr(app, "output_from_path", output_from_path)

    result = app.main(
        [
            "--slicer", "creality",
            "--printer", "K2 Plus",
            "--filament", "Generic PETG",
            "--process", "0.12mm PETG",
            "--input", "models/cube.stl",
            "--output", "/out/k2",
            "--no-prompt",
        ]
    )

    assert result == 0
    assert select_presets.call_args.kwargs == {
        "printer": "K2 Plus",
        "filament": "Generic PETG",
        "process": "0.12mm PETG",
        "prompt": False,
    }
    input_from_path.assert_called_once_with(Path("models/cube.stl"))
    output_from_path.assert_called_once_with(Path("/out/k2"))
    app.SlicingService.return_value.slice.assert_called_once_with(
        single.models[0], Path("/out/k2"), select_presets.return_value
    )
    assert "Sliced cube.stl" in capsys.readouterr().out


def test_no_prompt_uses_the_configured_output_folder_by_default(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --output, --no-prompt slices into the configured output folder."""
    _no_prompts(monkeypatch)
    monkeypatch.setattr(app, "input_from_path", Mock(return_value=_single_input()))
    output_from_path = Mock(return_value=Path("/out"))
    monkeypatch.setattr(app, "output_from_path", output_from_path)

    assert app.main(["--slicer", "bambu", "--input", "cube.stl", "--no-prompt"]) == 0
    output_from_path.assert_called_once_with(Path("configured-path"))


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--no-prompt"], "--slicer is required when --no-prompt is used."),
        (["--slicer", "bambu", "--no-prompt"], "--input is required when --no-prompt is used."),
        (["--slicer", "bambu", "--printer", "X1C"], "Preset selection is not available for Bambu Studio"),
    ],
)
def test_missing_or_unusable_options_stop_with_a_reason(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    """Options that cannot be satisfied stop startup with a clear message."""
    _no_prompts(monkeypatch)

    assert app.main(arguments) == 1
    assert message in _all_output(capsys)
    assert not app.SlicingService.called


def test_unconfigured_slicer_on_the_command_line_is_refused(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Naming a slicer without config says what to set."""
    monkeypatch.setattr(app, "is_configured", Mock(return_value=False))

    assert app.main(["--slicer", "orca"]) == 1
    assert "OrcaSlicer is not configured. Set orca.executable" in _all_output(capsys)


def test_list_presets_prints_printers_then_exits(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--list-presets prints printer names, without the banner, and slices nothing."""
    library = Mock()
    selection = _selection()
    library.return_value.printers.return_value = [selection.printer]
    monkeypatch.setattr(app, "PresetLibrary", library)

    assert app.main(["--slicer", "creality", "--list-presets"]) == 0

    output = capsys.readouterr().out
    assert output == "Printers for Creality Print (use with --printer):\n  K2 Plus\n"
    assert not app.SlicingService.called


def test_list_presets_for_a_printer_prints_filaments_and_processes(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With --printer, the compatible filament and process names are listed."""
    selection = _selection()
    library = Mock()
    library.return_value.printers.return_value = [selection.printer]
    library.return_value.filaments_for.return_value = [selection.filament]
    library.return_value.processes_for.return_value = [selection.process]
    monkeypatch.setattr(app, "PresetLibrary", library)

    assert app.main(["--slicer", "creality", "--printer", "k2 plus", "--list-presets"]) == 0

    assert capsys.readouterr().out == (
        "Filaments for K2 Plus (use with --filament):\n  Generic PETG\n"
        "Processes for K2 Plus (use with --process):\n  0.12mm PETG\n"
    )


def test_config_option_is_used_to_find_the_configuration(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
) -> None:
    """--config is passed to the configuration lookup."""
    app.main(["--config", "~/my-batchslicer.yaml"])

    app.find_config_file.assert_called_once_with(Path("~/my-batchslicer.yaml"))


def test_missing_configuration_is_explained(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a configuration file, startup stops with the lookup's explanation."""
    monkeypatch.setattr(
        app,
        "find_config_file",
        Mock(side_effect=FileNotFoundError("No configuration file found. Run 'batchslicer setup'.")),
    )

    assert app.main([]) == 1
    assert "Run 'batchslicer setup'" in _all_output(capsys)


def test_setup_command_runs_setup_instead_of_slicing(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'batchslicer setup' runs setup and does not load a configuration."""
    run_setup = Mock()
    monkeypatch.setattr(app, "run_setup", run_setup)

    assert app.main(["setup", "--no-prompt", "--config", "/tmp/c.yaml"]) == 0
    assert run_setup.call_args.args[0].config == Path("/tmp/c.yaml")
    assert not app.find_config_file.called

    run_setup.side_effect = SlicerSelectionError("No usable slicer was found.")
    assert app.main(["setup"]) == 1
    assert "BatchSlicer setup failed: No usable slicer was found." in _all_output(capsys)


def test_errors_go_to_stderr_and_progress_to_stdout(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scripts can separate normal output from errors."""
    app.SlicingService.return_value.slice.return_value = _outcome(success=False, message="bad model")

    assert app.main([]) == 1

    captured = capsys.readouterr()
    assert "Slicing cube.stl with Bambu Studio..." in captured.out
    assert "Slicing cube.stl failed: bad model" in captured.err
    assert "failed" not in captured.out


def test_ctrl_c_during_slicing_stops_cleanly(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C while slicing gives a short message and exit status 130, not a traceback."""
    app.SlicingService.return_value.slice.side_effect = KeyboardInterrupt

    assert app.main([]) == 130

    captured = capsys.readouterr()
    assert captured.err.strip() == "Cancelled."
    assert "Traceback" not in captured.out + captured.err


def test_interrupted_batch_reports_what_was_done(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An interrupted batch keeps and reports the finished models and exits with 130."""
    models = (Path("/models/a.stl"), Path("/models/b.stl"), Path("/models/c.stl"))
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(return_value=SliceInput(root=Path("/models"), models=models, is_folder=True)),
    )
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(
        batch_directory=Path("/out/models-1"),
        outcomes=(_outcome(success=True, model="/models/a.stl"),),
        planned=3,
        interrupted_model=Path("/models/b.stl"),
    )

    assert app.main([]) == 130

    captured = capsys.readouterr()
    assert "Interrupted while slicing /models/b.stl; 1 model file(s) were not started." in captured.err
    assert "Sliced 1 of 3 model files" in captured.out
    assert "Output: /out/models-1" in captured.out


def test_unexpected_error_is_summarised_with_details_in_the_log(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A bug gives a one-line message and the log path; the traceback goes to the log."""
    app.SlicingService.return_value.slice.side_effect = RuntimeError("something broke")
    monkeypatch.setattr(app, "current_log_file", Mock(return_value=tmp_path / "batchslicer.log"))
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("batchslicer")
    logger.addHandler(handler)
    try:
        assert app.main([]) == 1
    finally:
        logger.removeHandler(handler)

    captured = capsys.readouterr()
    assert "unexpected error: RuntimeError: something broke" in captured.err
    assert f"Details were written to {tmp_path / 'batchslicer.log'}" in captured.err
    assert "Traceback" not in captured.err
    logged = [record for record in records if record.exc_info]
    assert logged and isinstance(logged[0].exc_info[1], RuntimeError)


def test_unexpected_error_before_logging_shows_the_traceback(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a log file to point to, the details are shown instead."""
    startup_mocks[1].side_effect = RuntimeError("config exploded")
    monkeypatch.setattr(app, "current_log_file", Mock(return_value=None))

    assert app.main([]) == 1

    err = capsys.readouterr().err
    assert "unexpected error" in err
    assert "Traceback" in err
    assert "RuntimeError: config exploded" in err


def _store_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *profiles: object) -> Path:
    """Use a real profile store in ``tmp_path`` holding ``profiles``."""
    from batchslicer.infrastructure.profiles import ProfileStore

    path = tmp_path / "profiles.yaml"
    store = ProfileStore(path)
    for profile in profiles:
        store.save(profile)  # type: ignore[arg-type]
    monkeypatch.setattr(app, "ProfileStore", ProfileStore)
    original_get_path = app.get_config.return_value.get_path.side_effect

    def get_path(section: str, key: str) -> Path:
        if (section, key) == ("paths", "profiles"):
            return path
        return original_get_path(section, key)

    app.get_config.return_value.get_path.side_effect = get_path
    return path


def test_each_run_is_remembered_and_can_be_saved_by_name(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The run's choices are saved as 'last', and under --save-profile's name."""
    from batchslicer.infrastructure.profiles import ProfileStore

    path = _store_with(monkeypatch, tmp_path)

    assert app.main(["--save-profile", "bambu-cube"]) == 0

    saved = ProfileStore(path).load()
    assert set(saved) == {"last", "bambu-cube"}
    assert saved["last"].targets[0].slicer == "bambu_studio"
    assert saved["last"].input == Path("/models/cube.stl")
    assert saved["last"].output == Path("/out")
    assert "Saved these choices as profile 'bambu-cube'." in capsys.readouterr().out


def test_profile_fills_choices_and_options_override_it(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A profile supplies choices; options on the command line win."""
    from batchslicer.domain.profiles import Profile

    _store_with(
        monkeypatch,
        tmp_path,
        Profile.single("k2", slicer="creality_print", printer="K2 Plus", filament="PETG",
                process="Fine", input=Path("/models/brackets"), output=Path("/out/k2")),
    )
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    select_presets = Mock(return_value=_selection())
    monkeypatch.setattr(app, "select_presets", select_presets)
    input_from_path = Mock(return_value=_single_input())
    monkeypatch.setattr(app, "input_from_path", input_from_path)
    output_from_path = Mock(return_value=Path("/out/k2"))
    monkeypatch.setattr(app, "output_from_path", output_from_path)
    _no_prompts(monkeypatch)

    assert app.main(["--profile", "K2", "--process", "Draft", "--no-prompt"]) == 0

    assert select_presets.call_args.kwargs == {
        "printer": "K2 Plus",
        "filament": "PETG",
        "process": "Draft",
        "prompt": False,
    }
    input_from_path.assert_called_once_with(Path("/models/brackets"))
    output_from_path.assert_called_once_with(Path("/out/k2"))


def test_saved_profiles_are_offered_when_no_choices_are_given(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Interactive runs without options start by offering the saved profiles."""
    from batchslicer.domain.profiles import Profile

    _store_with(monkeypatch, tmp_path, Profile.single("last", slicer="bambu_studio"))
    offered = Mock(return_value=None)
    monkeypatch.setattr(app, "prompt_for_profile", offered)

    app.main([])
    assert offered.call_count == 1

    app.main(["--slicer", "bambu"])
    app.main(["--no-prompt", "--slicer", "bambu", "--input", "x.stl"])
    assert offered.call_count == 1


def test_list_and_delete_profiles(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--list-profiles shows them (last run first); --delete-profile removes one."""
    from batchslicer.domain.profiles import Profile

    path = _store_with(
        monkeypatch, tmp_path, Profile.single("k2", slicer="creality_print"), Profile.single("last", slicer="orca")
    )

    assert app.main(["--list-profiles"]) == 0
    assert capsys.readouterr().out == (
        f"Saved profiles ({path}):\n"
        "  last (used by --last): orca\n"
        "  k2: creality_print\n"
    )

    assert app.main(["--delete-profile", "k2"]) == 0
    assert "Deleted profile 'k2'." in capsys.readouterr().out
    assert app.main(["--delete-profile", "k2"]) == 1
    assert "No profile named 'k2'" in capsys.readouterr().err


def test_invalid_profile_name_is_refused_before_anything_runs(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad --save-profile name stops at once, before any questions."""
    assert app.main(["--save-profile", "a/b"]) == 1
    assert "Invalid profile name 'a/b'" in capsys.readouterr().err
    assert not app.find_config_file.called


def _two_printer_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Save a Creality K2 profile and a Bambu profile."""
    from batchslicer.domain.profiles import Profile

    return _store_with(
        monkeypatch,
        tmp_path,
        Profile.single("k2", slicer="creality_print", printer="K2 Plus", filament="PETG", process="Fine"),
        Profile.single("bambu", slicer="bambu_studio", input=Path("/models/cube.stl")),
    )


def _two_targets_ready(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Make preset selection and input/output work without prompts; return select_presets."""
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    select_presets = Mock(return_value=_selection())
    monkeypatch.setattr(app, "select_presets", select_presets)
    monkeypatch.setattr(app, "input_from_path", Mock(return_value=_single_input()))
    monkeypatch.setattr(app, "output_from_path", Mock(return_value=Path("/out")))
    return select_presets


def test_several_profiles_slice_for_each_printer_into_its_own_folder(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each printer gets its own subfolder, heading and summary line."""
    _two_printer_store(monkeypatch, tmp_path)
    _two_targets_ready(monkeypatch)
    _no_prompts(monkeypatch)
    slice_calls = app.SlicingService.return_value.slice

    assert app.main(["--profile", "k2", "--profile", "bambu", "--no-prompt"]) == 0

    destinations = [call.args[1] for call in slice_calls.call_args_list]
    assert destinations == [Path("/out/K2 Plus"), Path("/out/Bambu Studio")]
    slicers = [call.kwargs["slicer"].key for call in app.OrcaBackend.call_args_list]
    assert slicers == ["creality_print", "bambu_studio"]
    output = capsys.readouterr().out
    assert "BatchSlicer ready. Slicing for 2 printers:" in output
    assert "=== Printer 1 of 2: Creality Print: K2 Plus / Generic PETG / 0.12mm PETG ===" in output
    assert "=== Printer 2 of 2: Bambu Studio ===" in output
    assert "Finished 2 printers: 2 without problems." in output


def test_a_failure_for_one_printer_fails_the_run(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other printers still slice, the summary marks the failure, and the exit status is 1."""
    _two_printer_store(monkeypatch, tmp_path)
    _two_targets_ready(monkeypatch)
    app.SlicingService.return_value.slice.side_effect = [
        _outcome(success=False, message="bad"),
        _outcome(success=True),
    ]

    assert app.main(["--profile", "k2", "--profile", "bambu", "--no-prompt"]) == 1

    output = capsys.readouterr().out
    assert "Finished 2 printers: 1 without problems." in output
    assert "FAILED Creality Print: K2 Plus" in output
    assert "ok     Bambu Studio" in output


def test_interrupting_one_printer_stops_the_rest(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C during a batch for the first printer stops the run; the rest are not started."""
    _two_printer_store(monkeypatch, tmp_path)
    _two_targets_ready(monkeypatch)
    folder = SliceInput(root=Path("/models"), models=(Path("/models/a.stl"),), is_folder=True)
    monkeypatch.setattr(app, "input_from_path", Mock(return_value=folder))
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(
        Path("/out/K2 Plus/models-1"), (), planned=1, interrupted_model=Path("/models/a.stl")
    )

    assert app.main(["--profile", "k2", "--profile", "bambu", "--no-prompt"]) == 130

    assert "1 more printer(s) were not started." in capsys.readouterr().err
    assert app.SlicingService.return_value.slice_batch.call_count == 1


def test_single_printer_options_cannot_be_combined_with_several_printers(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--printer and friends describe one printer, so they are refused for several."""
    _two_printer_store(monkeypatch, tmp_path)

    assert app.main(["--profile", "k2", "--profile", "bambu", "--printer", "X"]) == 1
    assert "cannot be combined with several printers" in capsys.readouterr().err


def test_another_printer_can_be_added_interactively_and_is_remembered(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Answering yes adds a printer; the whole run is saved as 'last' with both."""
    from batchslicer.infrastructure.profiles import ProfileStore

    path = _store_with(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "confirm", Mock(side_effect=[True, False]))
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(side_effect=[BAMBU_STUDIO, CREALITY_PRINT]))
    _two_targets_ready(monkeypatch)
    monkeypatch.setattr(app, "prompt_for_input", Mock(return_value=_single_input()))

    assert app.main([]) == 0

    assert app.SlicingService.return_value.slice.call_count == 2
    last = ProfileStore(path).get("last")
    assert [target.slicer for target in last.targets] == ["bambu_studio", "creality_print"]
    assert last.targets[1].printer == "K2 Plus"


def test_extra_printers_are_not_offered_when_choices_were_given(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runs set up on the command line are not interrupted by the extra-printer question."""
    app.main(["--slicer", "bambu"])

    assert not app.confirm.called


def test_same_printer_twice_gets_numbered_folders(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two targets for the same printer (say, two filaments) do not share a folder."""
    from batchslicer.domain.profiles import Profile

    _store_with(
        monkeypatch,
        tmp_path,
        Profile.single("petg", slicer="creality_print", printer="K2 Plus", filament="PETG", process="Fine"),
        Profile.single("pla", slicer="creality_print", printer="K2 Plus", filament="PLA", process="Fine"),
    )
    _two_targets_ready(monkeypatch)

    app.main(["--profile", "petg", "--profile", "pla", "--no-prompt", "--input", "cube.stl"])

    destinations = [call.args[1] for call in app.SlicingService.return_value.slice.call_args_list]
    assert destinations == [Path("/out/K2 Plus"), Path("/out/K2 Plus (2)")]


def test_same_printer_with_different_slicers_names_the_slicer(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The same printer sliced by two slicers gets folders that say which slicer."""
    from batchslicer.domain.profiles import Profile

    _store_with(
        monkeypatch,
        tmp_path,
        Profile.single("c", slicer="creality_print", printer="K2 Plus", filament="F", process="P"),
        Profile.single("o", slicer="orca", printer="K2 Plus", filament="F", process="P"),
    )
    _two_targets_ready(monkeypatch)

    app.main(["--profile", "c", "--profile", "o", "--no-prompt", "--input", "cube.stl"])

    destinations = [call.args[1] for call in app.SlicingService.return_value.slice.call_args_list]
    assert destinations == [
        Path("/out/K2 Plus (Creality Print)"),
        Path("/out/K2 Plus (OrcaSlicer)"),
    ]
