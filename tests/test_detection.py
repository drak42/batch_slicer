"""Tests for finding installed slicers and their settings folders."""

from pathlib import Path

from batchslicer.backends.detection import find_data_directory, find_installations


def _touch(path: Path) -> Path:
    """Create an empty file and its folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_finds_appimages_and_recommends_newest_stable(tmp_path: Path) -> None:
    """Stable releases come first, newest first; pre-releases last."""
    _touch(tmp_path / "Apps" / "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage")
    _touch(tmp_path / "Apps" / "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage")
    _touch(tmp_path / "Downloads" / "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.3.1.AppImage")
    _touch(tmp_path / "Downloads" / "OrcaSlicer-Linux-flatpak_V2.4.0_x86_64.flatpak")
    _touch(tmp_path / "Apps" / "CrealityPrint-V7.3.0.6157-x86_64-Release.AppImage")

    found = find_installations("orca", home=tmp_path, environ={"PATH": ""})

    assert [(item.version_text, item.prerelease) for item in found] == [
        ("2.4.0", False),
        ("2.3.1", False),
        ("2.5.0", True),
    ]


def test_finds_appimages_one_folder_down(tmp_path: Path) -> None:
    """AppImages kept in a subfolder of a searched folder are found."""
    _touch(tmp_path / "Applications" / "bambu" / "BambuStudio_ubu24-v02.08.04.57-20260922.AppImage")

    found = find_installations("bambu_studio", home=tmp_path, environ={"PATH": ""})

    assert [item.version_text for item in found] == ["2.8.4.57"]


def test_finds_programs_on_path(tmp_path: Path) -> None:
    """A slicer installed as a regular program on PATH is found."""
    program = _touch(tmp_path / "bin" / "orca-slicer")
    program.chmod(0o755)

    found = find_installations("orca", home=tmp_path / "home", environ={"PATH": str(tmp_path / "bin")})

    assert [item.executable for item in found] == [program]


def test_nothing_installed(tmp_path: Path) -> None:
    """No matching files means no installations."""
    assert find_installations("creality_print", home=tmp_path, environ={"PATH": ""}) == []


def test_settings_folder_is_found_only_once_opened(tmp_path: Path) -> None:
    """The settings folder exists only after the slicer has been opened."""
    environ = {"XDG_CONFIG_HOME": str(tmp_path / "config")}
    assert find_data_directory("orca", home=tmp_path, environ=environ) is None

    (tmp_path / "config" / "OrcaSlicer").mkdir(parents=True)

    assert find_data_directory("orca", home=tmp_path, environ=environ) == tmp_path / "config" / "OrcaSlicer"


def test_creality_settings_folder_matches_the_program_version(tmp_path: Path) -> None:
    """Creality Print's per-version settings folder is matched to the program."""
    base = tmp_path / ".config" / "Creality" / "Creality Print"
    for version in ("7.0", "7.2", "7.3"):
        (base / version).mkdir(parents=True)
    _touch(tmp_path / "Apps" / "CrealityPrint-V7.2.1.5476-x86_64-Release.AppImage")
    environ = {"PATH": ""}
    installation = find_installations("creality_print", home=tmp_path, environ=environ)[0]

    assert find_data_directory("creality_print", installation, home=tmp_path, environ=environ) == base / "7.2"
    assert find_data_directory("creality_print", home=tmp_path, environ=environ) == base / "7.3"
