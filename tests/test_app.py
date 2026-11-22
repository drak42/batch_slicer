"""Tests for the BatchSlicer application bootstrap."""

import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer import app
from batchslicer.backends.slicers import BAMBU_STUDIO as _REAL_BAMBU_STUDIO
from batchslicer.backends.slicers import CREALITY_PRINT
from batchslicer.backends.slicers import SLICERS as _REAL_SLICERS
from batchslicer.cli.file_prompt import SliceInput
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.services.slicing import BatchOutcome, SliceOutcome
from conftest import FakeMoonraker, FakeOctoPrint


def _all_output(capsys: pytest.CaptureFixture[str]) -> str:
    """Return everything printed, normal output and errors together."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _single_input() -> SliceInput:
    """Return a one-file slicing input."""
    return SliceInput(root=Path("/models"), models=(Path("/models/cube.stl"),), is_folder=False)


BAMBU_STUDIO = replace(_REAL_BAMBU_STUDIO, app_config_name=None)
"""Stands in for a slicer without preset selection (every real slicer now has it)."""

SLICERS = tuple(BAMBU_STUDIO if slicer.key == BAMBU_STUDIO.key else slicer for slicer in _REAL_SLICERS)


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
    config.section.return_value = None  # no 'printers' section
    monkeypatch.setattr(app, "find_config_file", Mock(return_value=Path("/settings/config.yaml")))
    monkeypatch.setattr(app, "confirm", Mock(return_value=False))
    monkeypatch.setattr(app, "ask_number", Mock(return_value=1))  # one copy
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
    monkeypatch.setattr(app, "SLICERS", SLICERS)
    monkeypatch.setattr(app, "get_slicer", lambda key: next(s for s in SLICERS if s.key == key))
    monkeypatch.setattr(app, "prompt_for_input", Mock(return_value=_single_input()))
    monkeypatch.setattr(app, "prompt_for_output", Mock(return_value=Path("/out")))
    monkeypatch.setattr(app, "OrcaBackend", Mock())
    monkeypatch.setattr(app, "write_report", Mock(return_value=(Path("/out/report.csv"), Path("/out/report.json"))))
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

    def slice_batch(models_arg, root, output, selection, *, jobs, on_start, on_result):
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
        interrupted=True,
        interrupted_models=(Path("/models/b.stl"),),
    )

    assert app.main([]) == 130

    captured = capsys.readouterr()
    assert "Interrupted while slicing /models/b.stl; 2 model file(s) were not sliced." in captured.err
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
        Path("/out/K2 Plus/models-1"),
        (),
        planned=1,
        interrupted=True,
        interrupted_models=(Path("/models/a.stl"),),
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


def test_doctor_command_reports_and_sets_the_exit_status(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'batchslicer doctor' runs the checks instead of slicing; problems give status 1."""
    run_doctor = Mock(return_value=0)
    monkeypatch.setattr(app, "run_doctor", run_doctor)

    assert app.main(["doctor"]) == 0
    assert "BatchSlicer v" not in capsys.readouterr().out
    assert not app.find_config_file.called

    run_doctor.return_value = 2
    assert app.main(["doctor"]) == 1


def _folder_batch(monkeypatch: pytest.MonkeyPatch, *outcomes: SliceOutcome) -> None:
    """Make the run slice a folder whose batch ends with ``outcomes``."""
    models = tuple(outcome.model for outcome in outcomes)
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(return_value=SliceInput(root=Path("/models"), models=models, is_folder=True)),
    )
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(
        Path("/out/models-1"), outcomes, planned=len(outcomes)
    )


def test_options_reach_the_slicing_service_and_are_shown(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--orient, --allow-newer-files and --jobs are used for slicing and shown before it."""
    _folder_batch(monkeypatch, _outcome(success=True, model="/models/a.stl"))

    assert app.main(["--orient", "retry", "--allow-newer-files", "--jobs", "2"]) == 0

    service_options = app.SlicingService.call_args.kwargs["options"]
    assert service_options == app.SliceOptions(orient="retry", allow_newer_files=True)
    assert app.SlicingService.return_value.slice_batch.call_args.kwargs["jobs"] == 2
    output = capsys.readouterr().out
    assert (
        "Options:  auto-orient models that fail, allow newer 3MF files, 2 models at a time"
        in output
    )
    assert "Report: /out/report.csv" in output


def test_orient_is_refused_for_creality_print(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Creality Print's CLI has no auto-orient, so --orient stops before slicing."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))

    assert app.main(["--orient", "always"]) == 1

    assert "Creality Print has no command-line auto-orient" in capsys.readouterr().err
    app.SlicingService.return_value.slice.assert_not_called()


def test_failures_an_option_may_fix_get_a_hint(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failures that --orient retry or --allow-newer-files may fix say so."""
    _folder_batch(
        monkeypatch,
        _outcome(success=False, message="Failed slicing the model. (x)", model="/models/a.stl"),
        _outcome(
            success=False,
            message="c.stl: One object has an empty first layer and can't be printed.",
            model="/models/c.stl",
        ),
        _outcome(success=False, message="Unsupported 3MF version.", model="/models/b.3mf"),
    )

    assert app.main([]) == 1

    err = capsys.readouterr().err
    assert "Hint: 2 model(s) failed in a way that is often down to how the part was saved" in err
    assert "--orient retry" in err
    assert "--allow-newer-files" in err


def test_batch_summary_shows_auto_oriented_models_and_totals(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The summary counts auto-oriented models and totals print time and filament."""
    oriented = replace(
        _outcome(success=True, model="/models/a.stl"),
        auto_oriented=True,
        stats=app.GcodeStats(7200.0, 1500.0, None, None),
    )
    _folder_batch(monkeypatch, oriented)

    assert app.main(["--orient", "retry"]) == 0

    output = capsys.readouterr().out
    assert "1 of them with auto-orient." in output
    assert "To print: 2h 0m, 1.50 kg filament" in output


def test_profile_slicing_settings_apply_unless_overridden(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile's orient and jobs are used; command-line options override them."""
    saved = app.Profile(name="farm", orient="always", jobs=3)
    app.ProfileStore.return_value.get.return_value = saved
    _folder_batch(monkeypatch, _outcome(success=True, model="/models/a.stl"))

    app.main(["--profile", "farm", "--jobs", "1"])

    assert app.SlicingService.call_args.kwargs["options"].orient == "always"
    assert app.SlicingService.return_value.slice_batch.call_args.kwargs["jobs"] == 1
    remembered = app.ProfileStore.return_value.save.call_args.args[0]
    assert (remembered.orient, remembered.jobs) == ("always", 1)


@pytest.mark.parametrize(
    ("seconds", "text"), [(2.54, "2.5s"), (113.8, "1m 54s"), (4554, "1h 15m 54s")]
)
def test_run_times_are_shown_briefly(seconds: float, text: str) -> None:
    """Batch times are shown in seconds, or minutes and hours when long."""
    assert app._short_time(seconds) == text


def test_exclude_leaves_out_models_and_says_how_many(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Matching models are not sliced, the run says how many were skipped, and it is remembered."""
    models = (Path("/models/a.stl"), Path("/models/Cura-5/bed.stl"), Path("/models/cura-6/x.stl"))
    monkeypatch.setattr(
        app, "prompt_for_input", Mock(return_value=SliceInput(Path("/models"), models, True))
    )
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(
        Path("/out/models-1"), (_outcome(success=True, model="/models/a.stl"),)
    )

    assert app.main(["--exclude", "Cura-*"]) == 0

    assert app.SlicingService.return_value.slice_batch.call_args.args[0] == (Path("/models/a.stl"),)
    assert "Skipping 2 model files matching --exclude Cura-*" in capsys.readouterr().out
    assert app.ProfileStore.return_value.save.call_args.args[0].exclude == ("Cura-*",)


def test_excluding_everything_stops_with_a_reason(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If every model matches, nothing is sliced and the reason is given."""
    monkeypatch.setattr(
        app,
        "prompt_for_input",
        Mock(return_value=SliceInput(Path("/models"), (Path("/models/a.stl"),), True)),
    )

    assert app.main(["--exclude", "*.stl"]) == 1

    assert "Every model file in /models matches --exclude *.stl" in capsys.readouterr().err
    app.SlicingService.return_value.slice_batch.assert_not_called()


def _printer(monkeypatch: pytest.MonkeyPatch, fake: FakeMoonraker | FakeOctoPrint, tmp_path: Path) -> Path:
    """Configure printer 'k2' at ``fake`` and make slicing give real G-code in ``tmp_path``."""
    config = app.get_config.return_value
    config.section.side_effect = lambda name: {"k2": {"url": fake.url}} if name == "printers" else None
    output = tmp_path / "out"
    monkeypatch.setattr(app, "prompt_for_output", Mock(return_value=output))
    job = output / "cube-20261122-073000"
    job.mkdir(parents=True)
    (job / "cube.gcode").write_text("G28\n")
    app.SlicingService.return_value.slice.return_value = SliceOutcome(
        success=True, model=Path("/models/cube.stl"), job_directory=job,
        gcode_files=(job / "cube.gcode",), message="", elapsed=1.0,
    )
    return output


def test_send_uploads_and_starts_a_single_model(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--send uploads the G-code and --start prints it; the printer is remembered, start is not."""
    from batchslicer.infrastructure.profiles import ProfileStore

    store = _store_with(monkeypatch, tmp_path)
    _printer(monkeypatch, fake_moonraker, tmp_path)

    assert app.main(["--send", "K2", "--start"]) == 0

    out = capsys.readouterr().out
    assert f"Send to:  k2 ({fake_moonraker.url}), then start printing" in out
    assert "answers." in out
    assert "[1/1] cube.gcode ... sent" in out
    assert "Printing cube.gcode on k2." in out
    assert fake_moonraker.files == {"cube.gcode": b"G28\n"}
    assert fake_moonraker.forms[0]["print"] == "true"
    last = ProfileStore(store).get("last")
    assert last.targets[0].send == "k2"
    assert "start:" not in store.read_text(encoding="utf-8")



def test_send_to_an_octoprint_printer(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_octoprint: FakeOctoPrint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A printer configured with type: octoprint is checked and sent to through OctoPrint."""
    _store_with(monkeypatch, tmp_path)
    _printer(monkeypatch, fake_octoprint, tmp_path)
    app.get_config.return_value.section.side_effect = lambda name: (
        {"ender": {"type": "octoprint", "url": fake_octoprint.url, "api_key": fake_octoprint.api_key}}
        if name == "printers"
        else None
    )

    assert app.main(["--send", "ender", "--start"]) == 0

    out = capsys.readouterr().out
    assert f"Printer ender (OctoPrint, {fake_octoprint.url}) answers." in out
    assert "Printing cube.gcode on ender." in out
    assert fake_octoprint.files == {"cube.gcode": b"G28\n"}

def test_send_keeps_a_batchs_folders(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A folder's G-code goes into the batch folder on the printer; failed models are skipped."""
    output = _printer(monkeypatch, fake_moonraker, tmp_path)
    batch = output / "models-20261122-073000"
    job = batch / "kits" / "arm"
    job.mkdir(parents=True)
    (job / "arm.gcode").write_text("G1\n")
    good = SliceOutcome(True, Path("/models/kits/arm.stl"), job, (job / "arm.gcode",), "", 1.0)
    bad = SliceOutcome(False, Path("/models/x.stl"), batch / "x", (), "Failed", 1.0)
    _folder_batch(monkeypatch, good, bad)
    app.SlicingService.return_value.slice_batch.return_value = BatchOutcome(batch, (good, bad), planned=2)

    assert app.main(["--send", "k2"]) == 1  # the failed model fails the run

    assert fake_moonraker.files == {"models-20261122-073000/kits/arm.gcode": b"G1\n"}
    assert "Sent 1 of 1 file to k2." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "folder", "message"),
    [
        (["--send", "voron"], False, "No printer named 'voron'.*configured: k2"),
        (["--start"], False, "--start needs --send"),
        (["--send", "k2", "--start"], True, "single model file, not a folder"),
    ],
)
def test_send_problems_stop_before_slicing(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    folder: bool,
    message: str,
) -> None:
    """An unknown printer or an impossible --start is refused before anything is sliced."""
    _printer(monkeypatch, fake_moonraker, tmp_path)
    monkeypatch.setattr(app, "prompt_for_printer", Mock(return_value=None))  # "Don't send"
    if folder:
        _folder_batch(monkeypatch, _outcome(success=True))

    assert app.main(arguments) == 1

    assert re.search(message, _all_output(capsys))
    app.SlicingService.return_value.slice.assert_not_called()
    app.SlicingService.return_value.slice_batch.assert_not_called()


def test_unreachable_printer_stops_before_slicing(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A printer that does not answer stops the run before a long batch is sliced."""
    _printer(monkeypatch, fake_moonraker, tmp_path)
    fake_moonraker.api_key = "secret"

    assert app.main(["--send", "k2"]) == 1

    assert "refused access (HTTP 401)" in _all_output(capsys)
    app.SlicingService.return_value.slice.assert_not_called()


def test_no_send_overrides_a_profile_that_sends(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
) -> None:
    """A profile's printer is used unless --no-send is given."""
    from batchslicer.domain.profiles import Profile, Target

    _store_with(monkeypatch, tmp_path, Profile("k2", targets=(Target(slicer="bambu_studio", send="k2"),)))
    _printer(monkeypatch, fake_moonraker, tmp_path)

    assert app.main(["--profile", "k2", "--no-send"]) == 0
    assert fake_moonraker.files == {}
    assert app.main(["--profile", "k2"]) == 0
    assert list(fake_moonraker.files) == ["cube.gcode"]


def test_a_file_the_printer_refuses_fails_the_run(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sliced but not sent is reported as a failure."""
    _printer(monkeypatch, fake_moonraker, tmp_path)
    fake_moonraker.fail_names = {"cube.gcode"}

    assert app.main(["--send", "k2"]) == 1

    output = _all_output(capsys)
    assert "FAILED:" in output and "Bad file cube.gcode" in output
    assert "1 file(s) did not reach k2" in output


def test_printer_address_can_be_given_without_configuration(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--send with an address works with no 'printers' section, and is remembered as given."""
    from batchslicer.infrastructure.profiles import ProfileStore

    store = _store_with(monkeypatch, tmp_path)
    _printer(monkeypatch, fake_moonraker, tmp_path)
    app.get_config.return_value.section.side_effect = lambda name: None
    address = fake_moonraker.url.removeprefix("http://")

    assert app.main(["--send", address]) == 0

    assert list(fake_moonraker.files) == ["cube.gcode"]
    assert f"Send to:  {address} ({fake_moonraker.url})" in capsys.readouterr().out
    assert ProfileStore(store).get("last").targets[0].send == address


def test_interactive_run_asks_whether_to_send(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
) -> None:
    """With a printer configured, an interactive run asks; the answer is used and remembered."""
    from batchslicer.domain.printers import PrinterHost
    from batchslicer.infrastructure.profiles import ProfileStore

    store = _store_with(monkeypatch, tmp_path)
    _printer(monkeypatch, fake_moonraker, tmp_path)
    ask = Mock(side_effect=lambda hosts, last: hosts[0])
    monkeypatch.setattr(app, "prompt_for_printer", ask)
    monkeypatch.setattr(app, "prompt_for_profile", Mock(return_value=None))  # choose everything

    assert app.main([]) == 0

    assert ask.call_args.args[0] == [PrinterHost("k2", fake_moonraker.url)]
    assert list(fake_moonraker.files) == ["cube.gcode"]
    assert ProfileStore(store).get("last").targets[0].send == "k2"

    # The next run offers the printer used last time as the default.
    assert app.main([]) == 0
    assert ask.call_args.kwargs["last"] == PrinterHost("k2", fake_moonraker.url)


@pytest.mark.parametrize(
    "arguments", [["--no-send"], ["--send", "k2"], ["--profile", "k2"]], ids=["no-send", "send", "profile"]
)
def test_no_question_when_sending_is_already_decided(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_moonraker: FakeMoonraker,
    arguments: list[str],
) -> None:
    """--send, --no-send or a profile settle it, so nothing is asked."""
    from batchslicer.domain.profiles import Profile, Target

    _store_with(monkeypatch, tmp_path, Profile("k2", targets=(Target(slicer="bambu_studio"),)))
    _printer(monkeypatch, fake_moonraker, tmp_path)
    monkeypatch.setattr(app, "prompt_for_profile", Mock(return_value=None))
    ask = Mock(side_effect=AssertionError("asked"))
    monkeypatch.setattr(app, "prompt_for_printer", ask)

    assert app.main(arguments) == 0
    ask.assert_not_called()


def test_no_question_without_any_printer_to_offer(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """People who never send are never asked."""
    _store_with(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "prompt_for_printer", Mock(side_effect=AssertionError("asked")))

    assert app.main([]) == 0


def _kit_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the run slice a folder with two loose models in one subfolder."""
    _folder_batch(
        monkeypatch,
        _outcome(success=True, model="/models/kit/a.stl"),
        _outcome(success=True, model="/models/kit/b.stl"),
    )


def test_folder_run_asks_whether_to_use_plates(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With loose models sharing a folder, the run asks; the answer is used and remembered."""
    from batchslicer.infrastructure.profiles import ProfileStore

    store = _store_with(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "prompt_for_profile", Mock(return_value=None))
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=_REAL_SLICERS[0]))  # OrcaSlicer
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    _kit_batch(monkeypatch)
    questions: list[str] = []

    def answer(question: str, **kwargs: object) -> bool:
        questions.append(question)
        return question.startswith("Put the models")

    monkeypatch.setattr(app, "confirm", answer)

    assert app.main([]) == 0

    asked = [q for q in questions if q.startswith("Put the models")]
    assert asked == [
        "Put the models in each folder together on plates? (2 models in 1 folder could share "
        "plates; 3MF projects keep their own)"
    ]
    assert app.SlicingService.call_args.kwargs["options"].plates is True
    assert ProfileStore(store).get("last").plates is True


@pytest.mark.parametrize("arguments", [["--plates"], ["--no-plates"]])
def test_plates_option_is_not_asked(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    """--plates or --no-plates decides without a question."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=_REAL_SLICERS[0]))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    _kit_batch(monkeypatch)
    confirm = Mock(return_value=False)
    monkeypatch.setattr(app, "confirm", confirm)

    assert app.main(arguments) == 0

    assert not any("plates" in str(call) for call in confirm.call_args_list)
    assert app.SlicingService.call_args.kwargs["options"].plates is (arguments == ["--plates"])


def test_plates_are_refused_for_creality_print(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Creality Print cannot arrange from its command line, so --plates stops before slicing."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    _kit_batch(monkeypatch)

    assert app.main(["--plates"]) == 1

    assert "cannot arrange models" in _all_output(capsys)
    app.SlicingService.return_value.slice_batch.assert_not_called()


def test_summary_counts_models_on_plates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plate of several models counts each model, and the plates are totalled."""
    monkeypatch.setattr(app, "write_report", Mock(return_value=(Path("/out/report.csv"), Path("/out/r.json"))))
    job = Path("/out/models-1/kit/plates")
    together = SliceOutcome(
        True, Path("/models/kit"), job, (job / "kit_plate_1.gcode", job / "kit_plate_2.gcode"),
        "", 5.0, models=(Path("/models/kit/a.stl"), Path("/models/kit/b.stl"), Path("/models/kit/c.stl")),
    )
    batch = BatchOutcome(Path("/out/models-1"), (together, _outcome(success=True)), planned=4)

    app._report_batch(batch, Path("/models"), app.SliceOptions())

    out = capsys.readouterr().out
    assert "Sliced 4 of 4 model files" in out
    assert "3 of them together on 2 plates." in out


def test_single_model_run_asks_for_copies(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An interactive single-model run asks how many copies, uses the answer and reports it."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=_REAL_SLICERS[0]))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    ask = Mock(return_value=5)
    monkeypatch.setattr(app, "ask_number", ask)
    job = Path("/out/cube-1")
    app.SlicingService.return_value.slice.return_value = SliceOutcome(
        True, Path("/models/cube.stl"), job, (job / "cube.gcode",), "", 2.0, copies=5
    )

    assert app.main([]) == 0

    assert ask.call_args.args[0] == "How many copies of cube.stl?"
    assert app.SlicingService.call_args.kwargs["options"].copies == 5
    assert "Sliced cube.stl (5 copies on 1 plate)" in capsys.readouterr().out


def test_copies_are_not_asked_for_folders_or_projects(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Folders and 3MF projects are never copied, so nothing is asked."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=_REAL_SLICERS[0]))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    ask = Mock(side_effect=AssertionError("asked"))
    monkeypatch.setattr(app, "ask_number", ask)
    project = SliceInput(root=Path("/models"), models=(Path("/models/kit.3mf"),), is_folder=False)
    monkeypatch.setattr(app, "prompt_for_input", Mock(return_value=project))

    assert app.main([]) == 0
    _kit_batch(monkeypatch)
    assert app.main(["--no-plates"]) == 0


@pytest.mark.parametrize(
    ("models", "is_folder", "message"),
    [
        (("/models/kit/a.stl",), True, "not a folder"),
        (("/models/kit.3mf",), False, "keeps its own plates"),
    ],
)
def test_copies_on_the_command_line_are_refused_where_they_cannot_apply(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    models: tuple[str, ...],
    is_folder: bool,
    message: str,
) -> None:
    """--copies with a folder or a 3MF project stops before slicing."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=_REAL_SLICERS[0]))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    chosen = SliceInput(root=Path("/models"), models=tuple(Path(m) for m in models), is_folder=is_folder)
    monkeypatch.setattr(app, "prompt_for_input", Mock(return_value=chosen))

    assert app.main(["--copies", "3", "--no-plates"]) == 1

    assert message in _all_output(capsys)
    app.SlicingService.return_value.slice.assert_not_called()


def test_a_profiles_copies_are_left_out_for_a_folder(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Copies saved with a single model do not stop a later folder run from the same profile."""
    from batchslicer.domain.profiles import Profile, Target

    _store_with(monkeypatch, tmp_path, Profile("six", targets=(Target(slicer="orca"),), copies=6))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))
    _kit_batch(monkeypatch)

    assert app.main(["--profile", "six", "--no-plates"]) == 0

    assert "Not making 6 copies" in capsys.readouterr().out
    assert app.SlicingService.call_args.kwargs["options"].copies == 1


def test_copies_are_refused_for_creality_print(
    startup_mocks: tuple[Mock, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Creality Print cannot clone from its command line."""
    monkeypatch.setattr(app, "prompt_for_slicer", Mock(return_value=CREALITY_PRINT))
    monkeypatch.setattr(app, "PresetLibrary", Mock())
    monkeypatch.setattr(app, "select_presets", Mock(return_value=_selection()))

    assert app.main(["--copies", "2"]) == 1

    assert "cannot make copies" in _all_output(capsys)
