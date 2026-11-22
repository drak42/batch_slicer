"""Tests for colours, loaded filaments and matching a project's colours to them."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.domain.colours import colour_distance, colour_name, parse_colour
from batchslicer.domain.filaments import (
    LoadedFilament,
    ProjectFilament,
    describe_project_slot,
    match_slots,
)
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.infrastructure.moonraker import parse_creality_filaments
from batchslicer.services.filament_matching import build_matcher

K2_STATUS = {  # trimmed from a real Creality K2 Plus with one CFS
    "box": {
        "same_material": [["000003", "01b04ae", ["T1B"], "PETG"], ["000003", "09ea7ae", ["T1C"], "PETG"]],
        "T1": {
            "state": "connect",
            "vender": ["none", "unknown", "unknown", "none"],
            "color_value": ["0000000", "01b04ae", "09ea7ae", "-1"],
            "material_type": ["000003", "000003", "000003", "-1"],
        },
        "T2": {"state": "None", "vender": ["-1"] * 4, "color_value": ["-1"] * 4, "material_type": ["-1"] * 4},
    },
    "filament_rack": {"vender": "-1", "color_value": "0ffffff", "material_type": "000003"},
}


def test_colours_are_read_named_and_compared() -> None:
    """Hex codes (with or without # or alpha) become numbers, names and distances."""
    assert parse_colour("#1B04AE") == (0x1B, 0x04, 0xAE)
    assert parse_colour("ffffffff") == (255, 255, 255)
    assert parse_colour("blue") is None
    assert colour_name("#000000") == "black"
    assert colour_name("#9EA7AE") == "light grey"
    assert colour_name("nope") == ""
    assert colour_distance((0, 0, 0), (0, 0, 0)) == 0
    assert colour_distance((0, 0, 0), (0x1B, 0x04, 0xAE)) < colour_distance((0, 0, 0), (255, 255, 255))


def test_the_k2s_cfs_and_external_spool_are_read() -> None:
    """Loaded CFS slots and the external spool are found; empty slots and units are not."""
    assert parse_creality_filaments(K2_STATUS) == [
        LoadedFilament("1B", "#1B04AE", "PETG"),
        LoadedFilament("1C", "#9EA7AE", "PETG"),
        LoadedFilament("external", "#FFFFFF", "PETG"),
    ]
    assert parse_creality_filaments({}) == []
    assert LoadedFilament("1B", "#1B04AE", "PETG").describe() == "CFS 1B dark blue PETG"
    assert LoadedFilament("external", "#FFFFFF").describe() == "external spool white"


def test_each_project_colour_gets_the_closest_loaded_filament_once() -> None:
    """Pairs go best first, each loaded filament once; extra slots reuse the closest."""
    loaded = [
        LoadedFilament("1A", "#F5F5F5", "PLA"),
        LoadedFilament("1B", "#D02020", "PLA"),
        LoadedFilament("1C", "#101010", "PLA"),
    ]
    project = [ProjectFilament("#000000", "PLA"), ProjectFilament("#FFFFFF", "PLA"), ProjectFilament("#FF0000")]
    assert match_slots(project, loaded) == [2, 0, 1]

    two_blacks = match_slots([ProjectFilament("#000000"), ProjectFilament("#050505")], loaded)
    assert 2 in two_blacks and len(set(two_blacks)) == 2  # one gets the black, the other another filament
    assert match_slots(project + [ProjectFilament("#111111")], loaded)[3] == 2


def test_the_same_material_is_preferred_for_close_colours() -> None:
    """A slightly worse colour of the right material beats the right colour in another material."""
    loaded = [LoadedFilament("1A", "#000000", "PETG"), LoadedFilament("1B", "#202020", "PLA")]
    assert match_slots([ProjectFilament("#000000", "PLA")], loaded) == [1]
    with pytest.raises(ValueError):
        match_slots([ProjectFilament("#000000")], [])


def test_project_slots_are_described() -> None:
    """A slot shows its colour name and material."""
    assert describe_project_slot(ProjectFilament("#FFFFFF", "PETG")) == "white PETG"
    assert describe_project_slot(ProjectFilament("")) == "?"


def _preset(name: str, *, user: bool = False) -> Preset:
    return Preset(name, PresetKind.FILAMENT, Path(name), is_user=user)


def test_matcher_writes_coloured_files_of_the_loaded_material(tmp_path: Path) -> None:
    """Each project slot is sliced with a preset of the loaded material, in the loaded colour."""
    import zipfile

    pla, petg_generic, petg_mine = _preset("Generic PLA"), _preset("Generic PETG"), _preset("My PETG", user=True)
    types = {"Generic PLA": "PLA", "Generic PETG": ["PETG"], "My PETG": "PETG"}
    library = Mock()
    library.filaments_for.return_value = [pla, petg_generic, petg_mine]
    library.resolve.side_effect = lambda preset: {"filament_type": types[preset.name]}
    library.resolve_filament.side_effect = lambda preset, colour: {"name": preset.name, "filament_colour": [colour]}
    printer = Preset("K2", PresetKind.PRINTER, Path("k2"), is_user=False)
    selection = PresetSelection(printer, pla, Preset("Fine", PresetKind.PROCESS, Path("f"), is_user=False))
    loaded = [LoadedFilament("1B", "#1B04AE", "PETG"), LoadedFilament("external", "#FFFFFF", "PETG")]

    matcher = build_matcher(loaded, library, selection, logger=Mock())
    assert matcher is not None
    assert [item.preset.name for item in matcher.loaded] == ["My PETG", "My PETG"]
    assert build_matcher([], library, selection, logger=Mock()) is None

    model = tmp_path / "bumper.3mf"
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps({"filament_colour": ["#000000", "#FFFFFF"], "filament_type": ["PETG", "PETG"]}),
        )
    files = matcher.files_for(model, tmp_path / "job")

    assert files == [tmp_path / "job" / "presets" / "filament-1B.json", tmp_path / "job" / "presets" / "filament-external.json"]
    assert json.loads(files[0].read_text())["filament_colour"] == ["#1B04AE"]
    assert matcher.matches[model] == (
        "slot 1 (black PETG) -> CFS 1B dark blue PETG [My PETG]",
        "slot 2 (white PETG) -> external spool white PETG [My PETG]",
    )
    assert matcher.files_for(tmp_path / "cube.stl", tmp_path / "job") is None


def test_unknown_materials_use_the_chosen_filament() -> None:
    """A loaded filament without a known material, or one no preset has, uses slot 1's filament."""
    pla = _preset("Generic PLA")
    library = Mock()
    library.filaments_for.return_value = [pla]
    library.resolve.return_value = {"filament_type": "PLA"}
    library.resolve_filament.side_effect = lambda preset, colour: {}
    printer = Preset("K2", PresetKind.PRINTER, Path("k2"), is_user=False)
    selection = PresetSelection(printer, pla, Preset("Fine", PresetKind.PROCESS, Path("f"), is_user=False))

    matcher = build_matcher(
        [LoadedFilament("1A", "#000000", ""), LoadedFilament("1B", "#FFFFFF", "TPU")], library, selection, logger=Mock()
    )

    assert matcher is not None
    assert [item.preset.name for item in matcher.loaded] == ["Generic PLA", "Generic PLA"]
