"""Tests for command-line option parsing."""

from pathlib import Path

import pytest

from batchslicer.cli.arguments import RunOptions, parse_arguments


def test_no_arguments_means_ask_for_everything() -> None:
    """Without options every choice is left to the prompts."""
    assert parse_arguments([]) == RunOptions()


def test_all_choices_can_be_given() -> None:
    """Every prompt has a matching option."""
    options = parse_arguments(
        [
            "--slicer", "creality",
            "--printer", "Creality K2 Plus 0.4 nozzle",
            "--filament", "Generic PETG @Creality K2 Plus 0.4 nozzle",
            "--process", "0.20mm Standard @Creality K2 Plus 0.4 nozzle",
            "--input", "incoming/brackets",
            "--output", "/tmp/out",
            "--no-prompt",
        ]
    )

    assert options == RunOptions(
        slicer="creality_print",
        printer="Creality K2 Plus 0.4 nozzle",
        filament="Generic PETG @Creality K2 Plus 0.4 nozzle",
        process="0.20mm Standard @Creality K2 Plus 0.4 nozzle",
        input=Path("incoming/brackets"),
        output=Path("/tmp/out"),
        no_prompt=True,
    )


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("orca", "orca"),
        ("OrcaSlicer", "orca"),
        ("creality", "creality_print"),
        ("creality-print", "creality_print"),
        ("Creality Print", "creality_print"),
        ("bambu", "bambu_studio"),
        ("bambu_studio", "bambu_studio"),
    ],
)
def test_slicer_names_and_aliases(name: str, key: str) -> None:
    """Slicers can be named by short name, full name or config key."""
    assert parse_arguments(["--slicer", name]).slicer == key


def test_unknown_slicer_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown slicer exits with status 2 and lists the choices."""
    with pytest.raises(SystemExit) as raised:
        parse_arguments(["--slicer", "cura"])

    assert raised.value.code == 2
    assert "unknown slicer 'cura'" in capsys.readouterr().err


def test_list_presets_flag() -> None:
    """--list-presets is recognised."""
    assert parse_arguments(["--list-presets"]).list_presets


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """--version prints the product version and exits successfully."""
    with pytest.raises(SystemExit) as raised:
        parse_arguments(["--version"])

    assert raised.value.code == 0
    assert "BatchSlicer v" in capsys.readouterr().out


def test_setup_command_options(tmp_path: Path) -> None:
    """'setup' selects the setup command with its own options."""
    from batchslicer.cli.setup import SetupOptions

    options = parse_arguments(["setup", "--config", str(tmp_path / "c.yaml"), "--no-prompt", "--force"])

    assert options == SetupOptions(config=tmp_path / "c.yaml", no_prompt=True, force=True)


def test_setup_defaults_to_the_user_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without --config, setup writes the per-user configuration file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    options = parse_arguments(["setup"])

    assert options.config == tmp_path / "xdg" / "batchslicer" / "config.yaml"


def test_config_option_for_runs() -> None:
    """--config is accepted for normal runs."""
    assert parse_arguments(["--config", "my.yaml"]).config == Path("my.yaml")


def test_profile_options() -> None:
    """Profile options are parsed; --last means the 'last' profile."""
    assert parse_arguments(["--profile", "k2-petg"]).profiles == ("k2-petg",)
    assert parse_arguments(["--profile", "k2", "--profile", "ender"]).profiles == ("k2", "ender")
    assert parse_arguments(["--last"]).profiles == ("last",)
    assert parse_arguments(["--save-profile", "k2"]).save_profile == "k2"
    assert parse_arguments(["--list-profiles"]).list_profiles
    assert parse_arguments(["--delete-profile", "old"]).delete_profile == "old"


def test_profile_and_last_cannot_be_combined(capsys: pytest.CaptureFixture[str]) -> None:
    """--profile and --last both choose a starting profile, so only one may be given."""
    with pytest.raises(SystemExit) as raised:
        parse_arguments(["--profile", "k2", "--last"])

    assert raised.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_doctor_command_options() -> None:
    """'doctor' selects the doctor command, optionally with --config."""
    from batchslicer.cli.doctor import DoctorOptions

    assert parse_arguments(["doctor"]) == DoctorOptions()
    assert parse_arguments(["doctor", "--config", "c.yaml"]) == DoctorOptions(config=Path("c.yaml"))


def test_slicing_options() -> None:
    """--orient, --allow-newer-files and --jobs are parsed; unset means "not chosen"."""
    options = parse_arguments(["--orient", "Retry", "--allow-newer-files", "--jobs", "4"])

    assert isinstance(options, RunOptions)
    assert (options.orient, options.allow_newer_files, options.jobs) == ("retry", True, 4)
    unset = parse_arguments([])
    assert isinstance(unset, RunOptions)
    assert (unset.orient, unset.allow_newer_files, unset.jobs) == (None, None, None)
    refused = parse_arguments(["--no-allow-newer-files"])
    assert isinstance(refused, RunOptions)
    assert refused.allow_newer_files is False


@pytest.mark.parametrize(
    "arguments", [["--orient", "sideways"], ["--jobs", "0"], ["--jobs", "many"], ["--jobs", "65"]]
)
def test_bad_slicing_options_are_usage_errors(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid values stop with status 2 and say why."""
    with pytest.raises(SystemExit) as stopped:
        parse_arguments(arguments)

    assert stopped.value.code == 2
    assert "argument" in capsys.readouterr().err


def test_exclude_can_be_repeated() -> None:
    """Each --exclude adds a pattern; none given means "not chosen"."""
    options = parse_arguments(["--exclude", "Cura-*", "--exclude", "kits/old"])

    assert isinstance(options, RunOptions)
    assert options.exclude == ("Cura-*", "kits/old")
    unset = parse_arguments([])
    assert isinstance(unset, RunOptions)
    assert unset.exclude is None


def test_send_options() -> None:
    """--send names a printer, --no-send turns a profile's off, --start is a flag."""
    assert parse_arguments(["--send", "k2", "--start"]) == RunOptions(send="k2", start=True)
    assert parse_arguments(["--no-send"]) == RunOptions(send="")
    assert parse_arguments([]).send is None


def test_send_and_no_send_cannot_be_combined(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for both is a usage error."""
    with pytest.raises(SystemExit) as stopped:
        parse_arguments(["--send", "k2", "--no-send"])
    assert stopped.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_thumbnails_option() -> None:
    """--thumbnails / --no-thumbnails; unset means the default (on)."""
    assert parse_arguments([]).thumbnails is None
    assert parse_arguments(["--no-thumbnails"]).thumbnails is False
    assert parse_arguments(["--thumbnails"]).thumbnails is True
