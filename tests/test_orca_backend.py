"""Tests for the OrcaSlicer backend."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from orcabatch.backends.orca import OrcaBackend, OrcaResult
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
        ("orca", "--help"), capture_output=True, text=True, check=False
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

    result = backend.run(("orca", "--slice", "part.stl"))

    assert not result.success
    assert result.exit_code == 2
    assert result.stdout == "partial"
    assert result.stderr == "bad input"


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


def test_help_and_version_commands(backend: OrcaBackend) -> None:
    """Help and version use the configured base command."""
    assert backend.build_help_command()[-1] == "--help"
    assert backend.build_version_command()[-1] == "--version"
    assert backend.build_help_command()[0].endswith("Orca Slicer")
    assert backend.build_help_command()[1] == "--datadir"
    assert backend.build_help_command()[2].endswith("Orca Data")


def test_export_settings_command(backend: OrcaBackend, tmp_path: Path) -> None:
    """Export settings includes its output path as one argument."""
    output = tmp_path / "settings file.json"

    command = backend.build_export_settings_command(output)

    assert command[-2:] == ("--export-settings", str(output))


def test_slice_command_includes_input_output_and_requested_options(
    backend: OrcaBackend,
    tmp_path: Path,
) -> None:
    """Slice construction preserves paths and all supported optional flags."""
    command = backend.build_slice_command(
        tmp_path / "model file.stl",
        tmp_path / "output folder",
        orient=True,
        arrange=True,
        enable_timelapse=True,
        skip_modified_gcodes=True,
        no_check=True,
        load_settings=[tmp_path / "one.json", tmp_path / "two.json"],
        load_filaments=[tmp_path / "filament.json"],
    )

    assert command[0].endswith("Orca Slicer")
    assert command[1] == "--datadir"
    assert command[2].endswith("Orca Data")
    assert command[3:7] == (
        "--slice",
        str(tmp_path / "model file.stl"),
        "--outputdir",
        str(tmp_path / "output folder"),
    )
    assert command[7:] == (
        "--orient",
        "--arrange",
        "--enable-timelapse",
        "--skip-modified-gcodes",
        "--no-check",
        "--load-settings",
        str(tmp_path / "one.json"),
        "--load-settings",
        str(tmp_path / "two.json"),
        "--load-filaments",
        str(tmp_path / "filament.json"),
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

    assert run.call_args.args[0][-1] == "--orient"