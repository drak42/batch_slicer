"""Tests for the OrcaSlicer backend."""

from pathlib import Path
from unittest.mock import Mock

import os
import subprocess

import pytest

from orcabatch.backends.orca import DEFAULT_TIMEOUT_SECONDS, OrcaBackend, OrcaResult
from orcabatch.core.config import Config


@pytest.fixture
def backend(tmp_path: Path) -> OrcaBackend:
    """Create a backend with platform-independent temporary configuration."""
    config = Mock(spec=Config)
    config.get.side_effect = lambda section, key: {
        ("orca", "executable"): tmp_path / "Orca Slicer",
        ("orca", "datadir"): tmp_path / "Orca Data",
    }[(section, key)]
    return OrcaBackend(config=config, logger=Mock())


def test_orca_result_is_immutable() -> None:
    """OrcaResult has the required immutable fields."""
    result = OrcaResult(True, 0, "out", "", 0.1, ("orca", "--help"))

    assert result.success
    with pytest.raises(AttributeError):
        setattr(result, "success", False)


def test_run_captures_success_and_exact_command(
    backend: OrcaBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful subprocess output and command details are preserved."""
    run = Mock(return_value=Mock(returncode=0, stdout="help", stderr=""))
    monkeypatch.setattr("orcabatch.backends.orca.subprocess.run", run)

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
        "orcabatch.backends.orca.subprocess.run",
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
        "orcabatch.backends.orca.subprocess.run",
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
    monkeypatch.setattr("orcabatch.backends.orca.subprocess.run", run)

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
        "orcabatch.backends.orca.subprocess.run",
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


def test_configured_paths_accept_strings_and_paths() -> None:
    """Configured string and Path values are returned as pathlib Paths."""
    config = Mock(spec=Config)
    values = {
        ("orca", "executable"): "orca",
        ("orca", "datadir"): Path("orca-data"),
    }
    config.get.side_effect = lambda section, key: values[(section, key)]
    backend = OrcaBackend(config=config, logger=Mock())

    assert backend._configured_path("executable") == Path("orca")
    assert backend._configured_path("datadir") == Path("orca-data")


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

    monkeypatch.setattr("orcabatch.backends.orca.subprocess.run", fake_run)

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
    monkeypatch.setattr("orcabatch.backends.orca.subprocess.run", run)

    backend.slice(tmp_path / "model.stl", tmp_path / "out")

    assert run.call_args.kwargs["cwd"] is None


def test_relative_paths_are_made_absolute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative configured paths still work when OrcaSlicer runs elsewhere."""
    monkeypatch.chdir(tmp_path)
    config = Mock(spec=Config)
    values = {
        ("orca", "executable"): "bin/orca-slicer",
        ("orca", "datadir"): "orca-data",
    }
    config.get.side_effect = lambda section, key: values[(section, key)]
    backend = OrcaBackend(config=config, logger=Mock())

    command = backend.build_export_settings_command("settings.json")

    assert command == (
        str(tmp_path / "bin" / "orca-slicer"),
        "--datadir",
        str(tmp_path / "orca-data"),
        "--export-settings",
        str(tmp_path / "settings.json"),
    )


def test_bare_executable_name_is_left_for_path_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An executable given only by name is still found on PATH."""
    monkeypatch.chdir(tmp_path)
    config = Mock(spec=Config)
    values = {("orca", "executable"): "orca-slicer", ("orca", "datadir"): "data"}
    config.get.side_effect = lambda section, key: values[(section, key)]
    backend = OrcaBackend(config=config, logger=Mock())

    assert backend.build_help_command()[0] == "orca-slicer"


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


_REAL_ORCA = os.environ.get("ORCABATCH_TEST_ORCA_EXECUTABLE")


@pytest.mark.skipif(
    not _REAL_ORCA,
    reason="Set ORCABATCH_TEST_ORCA_EXECUTABLE to check against a real OrcaSlicer.",
)
def test_every_option_used_is_accepted_by_real_orca(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every option this backend emits appears in the real OrcaSlicer help text."""
    monkeypatch.chdir(tmp_path)
    config = Mock(spec=Config)
    values = {
        ("orca", "executable"): _REAL_ORCA,
        ("orca", "datadir"): tmp_path / "orca-data",
    }
    config.get.side_effect = lambda section, key: values[(section, key)]
    backend = OrcaBackend(config=config, logger=Mock(), timeout_seconds=120)

    help_text = backend.help().stdout
    command = backend.build_slice_command(
        tmp_path / "model.stl",
        tmp_path / "out",
        orient=True,
        arrange=True,
        enable_timelapse=True,
        skip_modified_gcodes=True,
        no_check=True,
        load_settings=[tmp_path / "machine.json"],
        load_filaments=[tmp_path / "filament.json"],
    ) + backend.build_export_settings_command(tmp_path / "settings.json")

    assert not (tmp_path / "result.json").exists()
    options = {argument for argument in command if argument.startswith("--")}
    assert "--slice option" in help_text
    for option in options:
        assert f" {option} " in help_text or f" {option}\n" in help_text, option
