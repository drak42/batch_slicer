"""Tests for reading the filaments a 3MF project lists."""

import json
import zipfile
from pathlib import Path

from batchslicer.backends.projects import is_project, project_filaments
from batchslicer.domain.filaments import ProjectFilament


def project(path: Path, settings: object) -> Path:
    """Write a 3MF holding ``settings`` as its project settings."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr("Metadata/project_settings.config", json.dumps(settings))
    return path


def test_slots_come_with_colour_material_and_name(tmp_path: Path) -> None:
    """Each listed filament is one slot, in order."""
    path = project(tmp_path / "bumper.3mf", {
        "filament_colour": ["#000000", "#FFFFFF"],
        "filament_type": ["PETG", "PETG"],
        "filament_settings_id": ["Bambu PETG HF @BBL X1C", "Bambu PETG HF @BBL X1C"],
    })

    assert project_filaments(path) == (
        ProjectFilament("#000000", "PETG", "Bambu PETG HF @BBL X1C"),
        ProjectFilament("#FFFFFF", "PETG", "Bambu PETG HF @BBL X1C"),
    )


def test_missing_details_are_left_empty(tmp_path: Path) -> None:
    """A project listing names but no colours still counts its slots."""
    path = project(tmp_path / "part.3MF", {"filament_settings_id": ["PLA", "PLA", "PETG"]})

    assert [slot.name for slot in project_filaments(path)] == ["PLA", "PLA", "PETG"]
    assert project_filaments(path)[0].colour == ""


def test_files_without_a_filament_list_give_none(tmp_path: Path) -> None:
    """STL files, plain 3MF files, broken files and odd settings give no slots."""
    stl = tmp_path / "cube.stl"
    stl.write_text("solid cube")
    plain = tmp_path / "plain.3mf"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
    broken = tmp_path / "broken.3mf"
    broken.write_text("not a zip")

    for path in (
        stl, plain, broken, tmp_path / "missing.3mf",
        project(tmp_path / "list.3mf", ["not", "settings"]),
        project(tmp_path / "text.3mf", {"filament_colour": "#FF0000"}),
    ):
        assert project_filaments(path) == (() if path.name != "text.3mf" else (ProjectFilament("#FF0000"),))


def test_projects_are_told_from_plain_3mf_files(tmp_path: Path) -> None:
    """Only a 3MF carrying a slicer's settings is a project."""
    plain = tmp_path / "plain.3mf"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
    broken = tmp_path / "broken.3mf"
    broken.write_text("not a zip")

    assert is_project(project(tmp_path / "saved.3mf", {}))
    assert not is_project(plain)
    assert not is_project(broken)
    assert not is_project(tmp_path / "cube.stl")
