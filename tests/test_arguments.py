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
