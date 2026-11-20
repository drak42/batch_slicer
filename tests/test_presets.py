"""Tests for reading and resolving slicer presets."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from orcabatch.backends.orca import OrcaBackend
from orcabatch.backends.presets import PresetError, PresetLibrary
from orcabatch.backends.profiles import find_system_profiles
from orcabatch.backends.slicers import CREALITY_PRINT, ORCASLICER, SlicerDefinition
from orcabatch.core.config import Config
from orcabatch.domain.presets import Preset, PresetKind, PresetSelection


K2 = "Creality K2 Plus 0.4 nozzle"
ENDER = "Creality Ender-3 V3 SE 0.4 nozzle"
USER_ID = "12345"


def _write(path: Path, data: dict[str, Any]) -> None:
    """Write one JSON preset file, creating its folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def datadir(tmp_path: Path) -> Path:
    """Create a small Creality Print style data directory."""
    root = tmp_path / "data"
    system = root / "system" / "Creality"
    conf = {
        "cloud": {"user_id": USER_ID, "token": "secret"},
        "orca_presets": [{"machine": ENDER}, {"machine": K2}, {"machine": "Default Printer"}],
        "presets": {"machine": K2},
    }
    root.mkdir()
    # Real settings files end with a checksum line after the JSON.
    (root / "Creality.conf").write_text(json.dumps(conf) + "\n# MD5 checksum abc\n")

    _write(system / "machine" / "common.json", {"name": "fdm_common", "nozzle_diameter": ["0.4"], "bed_x": "200"})
    _write(system / "machine" / "k2.json", {"name": K2, "inherits": "fdm_common", "instantiation": "true", "bed_x": "350"})
    _write(system / "machine" / "ender.json", {"name": ENDER, "inherits": "fdm_common", "instantiation": "true"})
    _write(system / "machine" / "unused.json", {"name": "Creality K1 0.4 nozzle", "inherits": "fdm_common", "instantiation": "true"})

    _write(system / "process" / "base.json", {"name": "fdm_process", "layer_height": "0.2", "wall_loops": "2"})
    _write(system / "process" / "nested" / "k2.json", {"name": f"0.20mm Standard @{K2}", "inherits": "fdm_process", "instantiation": "true", "compatible_printers": [K2]})
    _write(system / "process" / "ender.json", {"name": f"0.20mm Standard @{ENDER}", "inherits": "fdm_process", "instantiation": "true", "compatible_printers": [ENDER]})
    _write(system / "process" / "any.json", {"name": "0.30mm Draft", "inherits": "fdm_process", "instantiation": "true", "compatible_printers": []})

    _write(system / "filament" / "pla.json", {"name": f"Generic PLA @{K2}", "instantiation": "true", "compatible_printers": [K2], "nozzle_temperature": ["210"]})
    _write(system / "filament" / "petg.json", {"name": f"Generic PETG @{ENDER}", "instantiation": "true", "compatible_printers": [ENDER]})
    (system / "filament" / "colors.json").write_text('{"colors": []}')  # not a preset

    user = root / "user" / USER_ID
    _write(user / "process" / "mine.json", {"name": "My Fine", "inherits": f"0.20mm Standard @{K2}", "from": "User", "layer_height": "0.12"})
    _write(user / "filament" / "mine.json", {"name": "My PLA", "inherits": f"Generic PLA @{K2}", "from": "User", "nozzle_temperature": ["220"]})
    _write(root / "user" / "default" / "process" / "other.json", {"name": "Default Folder Preset", "inherits": f"0.20mm Standard @{K2}"})
    return root


def _library(datadir: Path) -> PresetLibrary:
    """Create a library for the fixture data directory."""
    return PresetLibrary(datadir, "Creality.conf")


def _names(presets: list[Preset]) -> list[str]:
    """Return preset names in order."""
    return [preset.name for preset in presets]


def test_printers_are_the_ones_added_in_the_slicer(datadir: Path) -> None:
    """Only printers added in the slicer are listed, in its order; unknown names are skipped."""
    printers = _library(datadir).printers()

    assert _names(printers) == [ENDER, K2]
    assert not any(printer.is_user for printer in printers)


def test_user_printers_come_first(datadir: Path) -> None:
    """Printers the user saved are listed before shipped ones."""
    _write(datadir / "user" / USER_ID / "machine" / "k2_mine.json", {"name": "My K2", "inherits": K2})

    printers = _library(datadir).printers()

    assert _names(printers) == ["My K2", ENDER, K2]
    assert printers[0].is_user


def test_presets_are_filtered_by_printer_with_user_presets_first(datadir: Path) -> None:
    """Filament and process lists contain only presets compatible with the printer."""
    library = _library(datadir)
    k2 = next(printer for printer in library.printers() if printer.name == K2)

    assert _names(library.processes_for(k2)) == ["My Fine", "0.20mm Standard @" + K2, "0.30mm Draft"]
    assert _names(library.filaments_for(k2)) == ["My PLA", f"Generic PLA @{K2}"]


def test_user_printer_uses_its_parents_compatibility(datadir: Path) -> None:
    """A user's printer matches presets made for the shipped printer it inherits from."""
    _write(datadir / "user" / USER_ID / "machine" / "k2_mine.json", {"name": "My K2", "inherits": K2})
    library = _library(datadir)
    mine = library.printers()[0]

    assert f"Generic PLA @{K2}" in _names(library.filaments_for(mine))


def test_non_instantiable_and_non_preset_files_are_not_offered(datadir: Path) -> None:
    """Base presets and files without a name are not offered."""
    library = _library(datadir)
    k2 = next(printer for printer in library.printers() if printer.name == K2)

    assert "fdm_process" not in _names(library.processes_for(k2))


def test_signed_out_user_falls_back_to_default_folder(datadir: Path) -> None:
    """Without a signed-in user, the default user folder is used."""
    conf = {"orca_presets": [{"machine": K2}]}
    (datadir / "Creality.conf").write_text(json.dumps(conf))
    library = _library(datadir)

    assert _names(library.processes_for(library.printers()[0]))[0] == "Default Folder Preset"


def test_resolve_merges_the_inheritance_chain(datadir: Path) -> None:
    """Resolved presets contain every inherited value, with the closest value winning."""
    library = _library(datadir)
    k2 = next(printer for printer in library.printers() if printer.name == K2)
    mine = library.processes_for(k2)[0]

    resolved = library.resolve(mine)

    assert resolved["layer_height"] == "0.12"
    assert resolved["wall_loops"] == "2"
    assert resolved["compatible_printers"] == [K2]
    assert resolved["type"] == "process"
    assert "inherits" not in resolved


def test_missing_parent_is_reported(datadir: Path) -> None:
    """A preset inheriting from an unknown preset raises PresetError."""
    _write(datadir / "user" / USER_ID / "process" / "broken.json", {"name": "Broken", "inherits": "Nowhere"})
    library = _library(datadir)
    broken = Preset("Broken", PresetKind.PROCESS, Path("x"), is_user=True)

    with pytest.raises(PresetError, match="Nowhere"):
        library.resolve(broken)


def test_inheritance_loops_are_reported(datadir: Path) -> None:
    """Presets that inherit from each other raise instead of looping forever."""
    user = datadir / "user" / USER_ID / "process"
    _write(user / "a.json", {"name": "A", "inherits": "B"})
    _write(user / "b.json", {"name": "B", "inherits": "A"})
    library = _library(datadir)

    with pytest.raises(PresetError, match="loops"):
        library.resolve(Preset("A", PresetKind.PROCESS, Path("x"), is_user=True))


def test_write_resolved_produces_cli_ready_files(datadir: Path, tmp_path: Path) -> None:
    """Written files are complete and carry the fields the slicer CLI checks."""
    library = _library(datadir)
    k2 = next(printer for printer in library.printers() if printer.name == K2)
    selection = PresetSelection(
        printer=k2,
        filament=library.filaments_for(k2)[0],
        process=library.processes_for(k2)[0],
    )

    settings, filaments = library.write_resolved(selection, tmp_path / "resolved")

    printer, process = (json.loads(path.read_text()) for path in settings)
    filament = json.loads(filaments[0].read_text())
    assert printer["from"] == "system"
    assert printer["printer_settings_id"] == K2
    assert printer["bed_x"] == "350"
    assert "inherits" not in printer
    assert process["from"] == "User"
    assert process["print_settings_id"] == "My Fine"
    assert process["layer_height"] == "0.12"
    assert filament["filament_settings_id"] == ["My PLA"]
    assert filament["nozzle_temperature"] == ["220"]
    assert filament["type"] == "filament"


def test_written_user_printer_keeps_link_to_its_shipped_printer(datadir: Path, tmp_path: Path) -> None:
    """The CLI matches a user's printer by its shipped parent, so that link is kept."""
    _write(datadir / "user" / USER_ID / "machine" / "k2_mine.json", {"name": "My K2", "inherits": K2, "bed_x": "300"})
    library = _library(datadir)
    mine = library.printers()[0]
    selection = PresetSelection(mine, library.filaments_for(mine)[0], library.processes_for(mine)[0])

    settings, _ = library.write_resolved(selection, tmp_path / "resolved")

    printer = json.loads(settings[0].read_text())
    assert printer["from"] == "User"
    assert printer["inherits"] == K2
    assert printer["printer_settings_id"] == "My K2"
    assert printer["bed_x"] == "300"


def test_shipped_presets_can_come_from_a_separate_folder(datadir: Path, tmp_path: Path) -> None:
    """OrcaSlicer's shipped presets live outside the data directory."""
    elsewhere = tmp_path / "profiles"
    (datadir / "system").rename(elsewhere)

    library = PresetLibrary(datadir, "Creality.conf", system_directory=elsewhere)

    assert _names(library.printers()) == [ENDER, K2]


def test_filaments_are_limited_to_those_visible_in_the_slicer(datadir: Path) -> None:
    """When the slicer records visible filaments, hidden shipped ones are left out."""
    _write(datadir / "system" / "Creality" / "filament" / "petg_k2.json", {"name": f"Generic PETG @{K2}", "instantiation": "true", "compatible_printers": [K2]})
    conf = json.loads((datadir / "Creality.conf").read_text().split("\n#")[0])
    conf["filaments"] = [f"Generic PETG @{K2}"]
    (datadir / "Creality.conf").write_text(json.dumps(conf))
    library = _library(datadir)
    k2 = next(printer for printer in library.printers() if printer.name == K2)

    assert _names(library.filaments_for(k2)) == ["My PLA", f"Generic PETG @{K2}"]


def test_unreadable_settings_file_is_reported(tmp_path: Path) -> None:
    """A missing or invalid slicer settings file raises PresetError."""
    with pytest.raises(PresetError, match="Cannot read"):
        PresetLibrary(tmp_path, "Creality.conf")

    (tmp_path / "Creality.conf").write_text("not json")
    with pytest.raises(PresetError, match="not valid JSON"):
        PresetLibrary(tmp_path, "Creality.conf")


def _real_slicer(slicer: SlicerDefinition, prefix: str) -> list[object]:
    """Return test parameters for a real slicer configured by environment variables."""
    executable = os.environ.get(f"ORCABATCH_TEST_{prefix}_EXECUTABLE")
    datadir = os.environ.get(f"ORCABATCH_TEST_{prefix}_DATADIR")
    return [
        pytest.param(
            slicer,
            executable,
            datadir,
            user_presets,
            id=f"{slicer.key}-{'user' if user_presets else 'built-in'}-presets",
            marks=pytest.mark.skipif(
                not (executable and datadir),
                reason=(
                    f"Set ORCABATCH_TEST_{prefix}_EXECUTABLE and ORCABATCH_TEST_{prefix}_DATADIR "
                    f"to slice with real {slicer.display_name} presets."
                ),
            ),
        )
        for user_presets in (True, False)
    ]


_REAL_SLICERS = _real_slicer(CREALITY_PRINT, "CREALITY") + _real_slicer(ORCASLICER, "ORCA")


def _write_cube(path: Path, size: float = 20.0) -> None:
    """Write a closed ASCII STL cube."""
    corners = [(x, y, z) for x in (0, size) for y in (0, size) for z in (0, size)]
    faces = [
        (0, 3, 1), (0, 2, 3), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
        (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5),
    ]
    lines = ["solid cube"]
    for face in faces:
        lines += [" facet normal 0 0 0", "  outer loop"]
        lines += [f"   vertex {' '.join(str(value) for value in corners[index])}" for index in face]
        lines += ["  endloop", " endfacet"]
    lines.append("endsolid cube")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize(("slicer", "executable", "datadir", "user_presets"), _REAL_SLICERS)
def test_real_slicer_slices_with_selected_presets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slicer: SlicerDefinition,
    executable: str,
    datadir: str,
    user_presets: bool,
) -> None:
    """Presets chosen from a real data directory produce G-code with the real slicer."""
    monkeypatch.chdir(tmp_path)
    data_directory = Path(datadir)
    system_directory = find_system_profiles(
        Path(executable), data_directory, tmp_path / "profile-cache", logger=Mock()
    )
    library = PresetLibrary(
        data_directory,
        str(slicer.app_config_name),
        system_directory=system_directory,
        logger=Mock(),
    )
    printer, filament, process = _first_usable_selection(library, prefer_user=user_presets)
    settings, filaments = library.write_resolved(
        PresetSelection(printer, filament, process), tmp_path / "resolved"
    )
    model = tmp_path / "cube.stl"
    _write_cube(model)
    config = Mock(spec=Config)
    values = {
        (slicer.key, "executable"): executable,
        (slicer.key, "datadir"): data_directory,
    }
    config.get.side_effect = lambda section, key: values[(section, key)]
    backend = OrcaBackend(slicer=slicer, config=config, logger=Mock(), timeout_seconds=300)

    result = backend.slice(
        model,
        tmp_path / "out",
        load_settings=settings,
        load_filaments=filaments,
    )

    assert result.success, (result.exit_code, (tmp_path / "out" / "result.json").read_text())
    gcode = (tmp_path / "out" / "plate_1.gcode").read_text(encoding="utf-8", errors="replace")
    assert f"; print_settings_id = {process.name}" in gcode
    assert f"; printer_settings_id = {printer.name}" in gcode


def _first_usable_selection(
    library: PresetLibrary,
    *,
    prefer_user: bool,
) -> tuple[Preset, Preset, Preset]:
    """Return a printer with compatible presets, preferring or avoiding the user's own."""
    for printer in library.printers():
        filaments = library.filaments_for(printer)
        processes = library.processes_for(printer)
        if not filaments or not processes:
            continue
        pick = (lambda presets: next((p for p in presets if p.is_user), None)) if prefer_user else (
            lambda presets: next((p for p in presets if not p.is_user), None)
        )
        filament, process = pick(filaments), pick(processes)
        if filament and process:
            return printer, filament, process
    pytest.skip("No printer with suitable presets in this data directory.")
