"""Tests for the supported slicer definitions."""

from pathlib import Path

import pytest

from orcabatch.backends.slicers import (
    BAMBU_STUDIO,
    CREALITY_PRINT,
    ORCASLICER,
    SLICERS,
    get_slicer,
    is_configured,
)
from orcabatch.core.config import Config


def test_all_three_slicers_are_offered_in_order() -> None:
    """OrcaSlicer, Creality Print and Bambu Studio are available, in that order."""
    assert [slicer.display_name for slicer in SLICERS] == [
        "OrcaSlicer",
        "Creality Print",
        "Bambu Studio",
    ]


def test_orcaslicer_keeps_the_existing_config_section() -> None:
    """Existing configurations with an orca: section keep working."""
    assert ORCASLICER.key == "orca"


def test_creality_print_needs_cli_mode_and_lacks_some_options() -> None:
    """Creality Print is launched with --cli and lacks orient/arrange/export options."""
    assert CREALITY_PRINT.launch_arguments == ("--cli",)
    assert not CREALITY_PRINT.supports("--orient")
    assert not CREALITY_PRINT.supports("--export-settings")
    assert CREALITY_PRINT.supports("--load-settings")
    assert BAMBU_STUDIO.supports("--orient")


def test_get_slicer_by_key() -> None:
    """Slicers are found by their configuration section name."""
    assert get_slicer("bambu_studio") is BAMBU_STUDIO
    with pytest.raises(KeyError):
        get_slicer("cura")


def test_is_configured_requires_both_paths(tmp_path: Path) -> None:
    """Only slicers with a non-empty executable and datadir count as configured."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            (
                "orca:",
                '  executable: "/opt/orca"',
                '  datadir: "/data/orca"',
                "creality_print:",
                '  executable: "/opt/creality"',
                '  datadir: ""',
                "",
            )
        ),
        encoding="utf-8",
    )
    config = Config(config_path)

    assert is_configured(ORCASLICER, config)
    assert not is_configured(CREALITY_PRINT, config)
    assert not is_configured(BAMBU_STUDIO, config)
