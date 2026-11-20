"""Tests for the OrcaSlicer backend."""

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.backends.orca import DEFAULT_TIMEOUT_SECONDS, OrcaBackend, OrcaResult
from batchslicer.backends.slicers import (
    BAMBU_STUDIO,
    CREALITY_PRINT,
    ORCASLICER,
    SlicerDefinition,
)
from batchslicer.core.config import Config
from conftest import write_config


@pytest.fixture
def backend(tmp_path: Path) -> OrcaBackend:
    """Create a backend with platform-independent temporary configuration."""
    config = write_config(
        tmp_path,
        {"orca": {"executable": tmp_path / "Orca Slicer", "datadir": tmp_path / "Orca Data"}},
    )
    return OrcaBackend(config=config, logger=Mock())


def test_orca_result_is_immutable() -> None:
    """OrcaResult has the required immutable fields."""
    result = OrcaResult(True, 0, "out", "", 0.1, ("orca", "--help"))

    assert result.success
    with pytest.raises(AttributeError):
        result.success = False


def test_run_captures_success_and_exact_command(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful subprocess output and command details are preserved."""
    run = Mock(return_value=Mock(returncode=0, stdout="help", stderr=""))
    monkeypatch.setattr("batchslicer.backends.orca.subprocess.run", run)

    result = backend.run(("orca", "--help"))

    assert result.success
    assert result.exit_code == 0
    assert result.stdout == "help"
    assert result.stderr == ""
    assert result.elapsed >= 0
    assert result.command == ("orca", "--help")
    run.assert_called_once_with(
        ("orca", "--help"),
        capture_output=True,
        text=True,
        check=False,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        cwd=None,
    )


def test_run_captures_nonzero_exit_and_stderr(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero Orca exits produce unsuccessful results without raising."""
    monkeypatch.setattr(
        "batchslicer.backends.orca.subprocess.run",
        Mock(return_value=Mock(returncode=2, stdout="partial", stderr="bad input")),
    )

    result = backend.run(("orca", "--slice", "0", "part.stl"))

    assert not result.success
    assert result.exit_code == 2
    assert result.stdout == "partial"
    assert result.stderr == "bad input"


def test_run_logs_stderr_when_command_fails(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed commands log Orca's error output so failures can be diagnosed."""
    monkeypatch.setattr(
        "batchslicer.backends.orca.subprocess.run",
        Mock(return_value=Mock(returncode=2, stdout="", stderr="no printer preset")),
    )

    backend.run(("orca", "--slice", "0", "part.stl"))

    logged = backend._logger.error.call_args.args
    assert "no printer preset" in logged


def test_run_stops_commands_that_exceed_the_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung OrcaSlicer process becomes an unsuccessful result, not a hang."""
    config = Mock(spec=Config)
    logger = Mock()
    backend = OrcaBackend(config=config, logger=logger, timeout_seconds=5)
    run = Mock(
        side_effect=subprocess.TimeoutExpired(
            cmd=("orca",), timeout=5, output=b"partial", stderr=b"still slicing"
        )
    )
    monkeypatch.setattr("batchslicer.backends.orca.subprocess.run", run)

    result = backend.run(("orca", "--slice", "0", "part.stl"))

    assert run.call_args.kwargs["timeout"] == 5
    assert not result.success
    assert result.exit_code == -1
    assert result.stdout == "partial"
    assert "still slicing" in result.stderr
    assert "timed out after 5 seconds" in result.stderr
    logger.error.assert_called_once()


def test_timeout_must_be_positive() -> None:
    """A zero or negative timeout is rejected."""
    with pytest.raises(ValueError):
        OrcaBackend(config=Mock(spec=Config), logger=Mock(), timeout_seconds=0)


def test_run_handles_process_start_failure(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expected process start failures become unsuccessful results."""
    monkeypatch.setattr(
        "batchslicer.backends.orca.subprocess.run",
        Mock(side_effect=FileNotFoundError("orca missing")),
    )

    result = backend.run(("missing-orca", "--version"))

    assert not result.success
    assert result.exit_code == -1
    assert result.stderr == "orca missing"


def test_help_command(backend: OrcaBackend) -> None:
    """Help uses the configured base command."""
    assert backend.build_help_command()[-1] == "--help"
    assert backend.build_help_command()[0].endswith("Orca Slicer")
    assert backend.build_help_command()[1] == "--datadir"
    assert backend.build_help_command()[2].endswith("Orca Data")


def test_export_settings_command(backend: OrcaBackend, tmp_path: Path) -> None:
    """Export settings includes its output path as one argument."""
    output = tmp_path / "settings file.json"

    command = backend.build_export_settings_command(output)

    assert command[-2:] == ("--export-settings", str(output))


def test_help_and_export_run_outside_the_working_directory(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Commands without --outputdir run in a scratch directory so result.json is not left behind."""
    monkeypatch.chdir(tmp_path)
    used_directories: list[Path] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> Mock:
        directory = Path(str(kwargs["cwd"]))
        used_directories.append(directory)
        (directory / "result.json").write_text("{}", encoding="utf-8")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("batchslicer.backends.orca.subprocess.run", fake_run)

    backend.help()
    backend.export_settings("settings.json")

    assert len(used_directories) == 2
    for directory in used_directories:
        assert directory != tmp_path
        assert not directory.exists()
    assert not (tmp_path / "result.json").exists()


def test_slice_keeps_working_directory(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Slicing writes result.json to --outputdir, so it runs from the current directory."""
    run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("batchslicer.backends.orca.subprocess.run", run)

    backend.slice(tmp_path / "model.stl", tmp_path / "out")

    assert run.call_args.kwargs["cwd"] is None


def test_relative_paths_are_made_absolute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative configured paths are relative to the configuration file, not the current folder."""
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / "settings"
    config = write_config(
        settings, {"orca": {"executable": "bin/orca-slicer", "datadir": "orca-data"}}
    )
    backend = OrcaBackend(config=config, logger=Mock())

    command = backend.build_export_settings_command("settings.json")

    assert command == (
        str(settings / "bin" / "orca-slicer"),
        "--datadir",
        str(settings / "orca-data"),
        "--export-settings",
        str(tmp_path / "settings.json"),
    )


def test_bare_executable_name_is_left_for_path_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An executable given only by name is still found on PATH."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    config = write_config(tmp_path, {"orca": {"executable": "orca-slicer", "datadir": "data"}})
    backend = OrcaBackend(config=config, logger=Mock())

    assert backend.build_help_command()[0] == "orca-slicer"


def test_bare_executable_name_found_on_path_is_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare executable name found on PATH becomes its full path."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    program = bin_directory / "orca-slicer"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_directory))
    config = write_config(tmp_path, {"orca": {"executable": "orca-slicer", "datadir": "data"}})

    assert OrcaBackend(config=config, logger=Mock()).build_help_command()[0] == str(program)


def test_home_folder_in_paths_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Paths written with ~ point into the home folder."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config = write_config(
        tmp_path,
        {"orca": {"executable": "~/Apps/Orca.AppImage", "datadir": "~/.config/OrcaSlicer"}},
    )

    command = OrcaBackend(config=config, logger=Mock()).build_help_command()

    assert command[0] == str(tmp_path / "home" / "Apps" / "Orca.AppImage")
    assert command[2] == str(tmp_path / "home" / ".config" / "OrcaSlicer")


def test_slice_command_follows_orca_cli_contract(
    backend: OrcaBackend,
    tmp_path: Path,
) -> None:
    """Slice selects a plate, passes option values, and ends with the model file."""
    command = backend.build_slice_command(
        tmp_path / "model file.stl",
        tmp_path / "output folder",
        orient=True,
        arrange=True,
        enable_timelapse=True,
        skip_modified_gcodes=True,
        no_check=True,
        load_settings=[tmp_path / "machine.json", tmp_path / "process.json"],
        load_filaments=[tmp_path / "filament.json"],
    )

    assert command[0].endswith("Orca Slicer")
    assert command[1] == "--datadir"
    assert command[2].endswith("Orca Data")
    assert command[3:] == (
        "--slice",
        "0",
        "--outputdir",
        str(tmp_path / "output folder"),
        "--orient",
        "1",
        "--arrange",
        "1",
        "--skip-modified-gcodes",
        "1",
        "--enable-timelapse",
        "--no-check",
        "--load-settings",
        f"{tmp_path / 'machine.json'};{tmp_path / 'process.json'}",
        "--load-filaments",
        str(tmp_path / "filament.json"),
        str(tmp_path / "model file.stl"),
    )


def test_minimal_slice_command(backend: OrcaBackend, tmp_path: Path) -> None:
    """Without options, slicing all plates needs only the plate, output and model."""
    command = backend.build_slice_command(tmp_path / "model.stl", tmp_path / "out")

    assert command[3:] == (
        "--slice",
        "0",
        "--outputdir",
        str(tmp_path / "out"),
        str(tmp_path / "model.stl"),
    )


def test_slice_command_selects_a_single_plate(backend: OrcaBackend, tmp_path: Path) -> None:
    """A specific plate number is passed to --slice."""
    command = backend.build_slice_command(tmp_path / "model.3mf", tmp_path / "out", plate=2)

    assert command[3:5] == ("--slice", "2")


def test_slice_command_rejects_negative_plate(backend: OrcaBackend, tmp_path: Path) -> None:
    """Negative plate numbers are invalid for OrcaSlicer."""
    with pytest.raises(ValueError):
        backend.build_slice_command(tmp_path / "model.stl", tmp_path / "out", plate=-1)


def test_slice_command_rejects_paths_containing_the_list_separator(
    backend: OrcaBackend,
    tmp_path: Path,
) -> None:
    """A ';' in a settings path would be split by OrcaSlicer, so it is refused."""
    with pytest.raises(ValueError):
        backend.build_slice_command(
            tmp_path / "model.stl",
            tmp_path / "out",
            load_settings=[tmp_path / "bad;name.json"],
        )


def test_slice_executes_the_constructed_command(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The public slice operation delegates to the controlled runner."""
    run = Mock(return_value=OrcaResult(True, 0, "", "", 0.01, ()))
    monkeypatch.setattr(backend, "run", run)

    backend.slice(tmp_path / "model.stl", tmp_path / "output", orient=True)

    executed = run.call_args.args[0]
    assert executed[-1] == str(tmp_path / "model.stl")
    assert ("--orient", "1") == executed[-3:-1]


def _backend_for(slicer: SlicerDefinition, tmp_path: Path) -> OrcaBackend:
    """Create a backend whose config only has a section for ``slicer``."""
    config = write_config(
        tmp_path,
        {
            slicer.key: {
                "executable": tmp_path / slicer.display_name,
                "datadir": tmp_path / f"{slicer.display_name} data",
            }
        },
    )
    return OrcaBackend(slicer=slicer, config=config, logger=Mock())


def test_backend_reads_the_selected_slicers_config_section(tmp_path: Path) -> None:
    """Each slicer's paths come from its own config section."""
    command = _backend_for(BAMBU_STUDIO, tmp_path).build_help_command()

    assert command == (
        str(tmp_path / "Bambu Studio"),
        "--datadir",
        str(tmp_path / "Bambu Studio data"),
        "--help",
    )


def test_creality_print_commands_start_with_cli_mode(tmp_path: Path) -> None:
    """Creality Print gets --cli straight after the executable."""
    command = _backend_for(CREALITY_PRINT, tmp_path).build_slice_command(
        tmp_path / "model.stl",
        tmp_path / "out",
        no_check=True,
    )

    assert command == (
        str(tmp_path / "Creality Print"),
        "--cli",
        "--datadir",
        str(tmp_path / "Creality Print data"),
        "--slice",
        "0",
        "--outputdir",
        str(tmp_path / "out"),
        "--need-gcode-file",
        "--no-check",
        str(tmp_path / "model.stl"),
    )


@pytest.mark.parametrize(
    "option",
    [{"orient": True}, {"arrange": True}, {"skip_modified_gcodes": True}],
)
def test_unsupported_slice_options_are_refused(tmp_path: Path, option: dict[str, bool]) -> None:
    """Options Creality Print lacks raise a clear error instead of a bad command."""
    backend = _backend_for(CREALITY_PRINT, tmp_path)

    with pytest.raises(ValueError, match="Creality Print does not support"):
        backend.build_slice_command(tmp_path / "model.stl", tmp_path / "out", **option)


def test_unsupported_export_settings_is_refused(tmp_path: Path) -> None:
    """Creality Print has no --export-settings."""
    with pytest.raises(ValueError, match="does not support --export-settings"):
        _backend_for(CREALITY_PRINT, tmp_path).build_export_settings_command("out.json")


def test_log_messages_name_the_selected_slicer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures are logged under the selected slicer's name."""
    backend = _backend_for(BAMBU_STUDIO, tmp_path)
    monkeypatch.setattr(
        "batchslicer.backends.orca.subprocess.run",
        Mock(return_value=Mock(returncode=1, stdout="", stderr="boom")),
    )

    backend.run(("bambu", "--help"))

    assert backend._logger.error.call_args.args[1] == "Bambu Studio"


_REAL_SLICERS = [
    pytest.param(
        slicer,
        os.environ.get(variable),
        id=slicer.key,
        marks=pytest.mark.skipif(
            not os.environ.get(variable),
            reason=f"Set {variable} to check against a real {slicer.display_name}.",
        ),
    )
    for slicer, variable in (
        (ORCASLICER, "BATCHSLICER_TEST_ORCA_EXECUTABLE"),
        (CREALITY_PRINT, "BATCHSLICER_TEST_CREALITY_EXECUTABLE"),
        (BAMBU_STUDIO, "BATCHSLICER_TEST_BAMBU_EXECUTABLE"),
    )
]


@pytest.mark.parametrize(("slicer", "executable"), _REAL_SLICERS)
def test_every_option_used_is_accepted_by_real_slicer(
    slicer: SlicerDefinition,
    executable: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every option the backend can send this slicer appears in its real help text."""
    monkeypatch.chdir(tmp_path)
    config = write_config(
        tmp_path / "settings",
        {slicer.key: {"executable": executable, "datadir": tmp_path / "slicer-data"}},
    )
    backend = OrcaBackend(slicer=slicer, config=config, logger=Mock(), timeout_seconds=120)

    help_result = backend.help()
    help_text = help_result.stdout + help_result.stderr
    command = backend.build_slice_command(
        tmp_path / "model.stl",
        tmp_path / "out",
        orient=slicer.supports("--orient"),
        arrange=slicer.supports("--arrange"),
        enable_timelapse=True,
        skip_modified_gcodes=slicer.supports("--skip-modified-gcodes"),
        no_check=True,
        load_settings=[tmp_path / "machine.json"],
        load_filaments=[tmp_path / "filament.json"],
    )
    if slicer.supports("--export-settings"):
        command += backend.build_export_settings_command(tmp_path / "settings.json")

    assert not (tmp_path / "result.json").exists()
    assert "--slice option" in help_text
    options = {
        argument
        for argument in command
        if argument.startswith("--") and argument not in slicer.launch_arguments
    }
    for option in options:
        assert f" {option} " in help_text or f" {option}\n" in help_text, option
