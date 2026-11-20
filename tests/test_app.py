"""Tests for the BatchSlicer application bootstrap."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer import app
from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, SLICERS
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.cli.file_prompt import SliceInput
from batchslicer.services.slicing import BatchOutcome, SliceOutcome


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
from batchslicer.cli.slicer_prompt import SlicerSelectionError


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
    assert "BatchSlicer startup failed: missing config" in capsys.readouterr().out


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
    output = capsys.readouterr().out
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

    assert "slicer_executable: Bambu Studio executable not found: /x" in capsys.readouterr().out

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
    output = capsys.readouterr().out
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
    output = capsys.readouterr().out
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
    output = capsys.readouterr().out
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
    assert message in capsys.readouterr().out
    assert not app.SlicingService.called


def test_unconfigured_slicer_on_the_command_line_is_refused(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Naming a slicer without config says what to set."""
    monkeypatch.setattr(app, "is_configured", Mock(return_value=False))

    assert app.main(["--slicer", "orca"]) == 1
    assert "OrcaSlicer is not configured. Set orca.executable" in capsys.readouterr().out


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
    assert "Run 'batchslicer setup'" in capsys.readouterr().out


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
    assert "BatchSlicer setup failed: No usable slicer was found." in capsys.readouterr().out
