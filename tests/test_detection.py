"""Tests for finding installed slicers and their settings folders."""

import plistlib
from pathlib import Path

import pytest

from batchslicer.backends import detection
from batchslicer.backends.detection import Installation, find_data_directory, find_installations
from conftest import fake_program


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
    program = fake_program(tmp_path / "bin" / "orca-slicer")

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


def _exe(path: Path) -> Path:
    return _touch(path)


@pytest.mark.usefixtures("windows")
def test_finds_windows_installs_and_portable_copies(tmp_path: Path) -> None:
    """Program Files, %LOCALAPPDATA%\\Programs and portable folders are searched on Windows."""
    program_files = tmp_path / "Program Files"
    local = tmp_path / "AppData" / "Local"
    home = tmp_path / "home"
    orca = _exe(program_files / "OrcaSlicer" / "orca-slicer.exe")
    portable = _exe(home / "Downloads" / "OrcaSlicer_Windows_V2.5.2_portable" / "orca-slicer.exe")
    creality = _exe(program_files / "Creality" / "Creality Print 7.0" / "CrealityPrint.exe")
    bambu = _exe(local / "Programs" / "Bambu Studio" / "bambu-studio.exe")
    environ = {"PATH": "", "ProgramFiles": str(program_files), "ProgramFiles(x86)": str(tmp_path / "x86"),
               "LOCALAPPDATA": str(local)}

    found = find_installations("orca", home=home, environ=environ)

    assert {(item.executable, item.version_text) for item in found} == {(orca, "unknown"), (portable, "2.5.2")}
    assert found[0].executable == portable  # a known version comes before an unknown one
    [creality_found] = find_installations("creality_print", home=home, environ=environ)
    assert (creality_found.executable, creality_found.version_text) == (creality, "7.0")
    assert [item.executable for item in find_installations("bambu_studio", home=home, environ=environ)] == [bambu]


@pytest.mark.usefixtures("windows")
def test_windows_settings_are_under_appdata(tmp_path: Path) -> None:
    """On Windows the slicers keep their settings in %APPDATA%."""
    roaming = tmp_path / "AppData" / "Roaming"
    (roaming / "OrcaSlicer").mkdir(parents=True)
    (roaming / "Creality" / "Creality Print" / "7.0").mkdir(parents=True)
    environ = {"APPDATA": str(roaming)}

    assert find_data_directory("orca", home=tmp_path, environ=environ) == roaming / "OrcaSlicer"
    assert find_data_directory("creality_print", home=tmp_path, environ=environ) == (
        roaming / "Creality" / "Creality Print" / "7.0"
    )
    assert find_data_directory("bambu_studio", home=tmp_path, environ=environ) is None
    assert find_data_directory("orca", home=tmp_path, environ={}) == roaming / "OrcaSlicer"  # ~/AppData/Roaming


def test_windows_version_comes_from_the_installed_programs_list() -> None:
    """The installed-programs list is matched by folder, however Windows wrote the path."""
    program = Path("C:/Program Files/OrcaSlicer/orca-slicer.exe")
    entries = [
        ("C:\\Program Files\\Bambu Studio", "02.09.01.70"),
        ('"c:\\program files\\orcaslicer\\"', "2.5.2"),
    ]

    assert detection._installed_version(program, entries) == (2, 5, 2)
    assert detection._installed_version(program, [("C:\\Program Files\\Other", "9.9")]) == ()
    assert detection._installed_version(program, [("C:\\Program Files\\OrcaSlicer", "")]) == ()


def test_uninstaller_folder_is_read_from_the_uninstall_command() -> None:
    """Without InstallLocation, the uninstaller's folder stands for the install folder."""
    assert detection._uninstaller_folder('"C:\\Program Files\\OrcaSlicer\\Uninstall.exe"') == (
        "C:\\Program Files\\OrcaSlicer"
    )
    assert detection._uninstaller_folder("C:\\Apps\\Slicer\\uninst.exe /S") == "C:\\Apps\\Slicer"
    assert detection._uninstaller_folder("") == ""


@pytest.mark.usefixtures("windows")
def test_installed_programs_list_wins_over_a_placeholder_file_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OrcaSlicer's program file says 2.0.0.0; the installed-programs list says 2.5.2."""
    program = _exe(tmp_path / "Program Files" / "OrcaSlicer" / "orca-slicer.exe")
    monkeypatch.setattr(detection, "_file_version", lambda _: (2, 0, 0))
    monkeypatch.setattr(detection, "_uninstall_entries", lambda: [(str(program.parent), "2.5.2")])

    assert detection._windows_installation(program).version == (2, 5, 2)

    monkeypatch.setattr(detection, "_uninstall_entries", list)
    assert detection._windows_installation(program).version == (2, 0, 0)


@pytest.mark.usefixtures("windows")
def test_creality_print_updated_in_place_uses_its_newest_settings(tmp_path: Path) -> None:
    """Seen on a real machine: Windows lists 7.2, settings are in 7.0 (old) and 7.3 (in use).

    Creality Print's hidden migration folders also contain "7.3" but are not settings.
    """
    base = tmp_path / "Roaming" / "Creality" / "Creality Print"
    for version in ("7.0", "7.3", ".7.3.staging-17913297740142173", ".migration-7.3"):
        (base / version).mkdir(parents=True)
    installation = Installation(executable=tmp_path / "CrealityPrint.exe", version=(7, 2, 0), prerelease=False)

    found = find_data_directory(
        "creality_print", installation, home=tmp_path, environ={"APPDATA": str(tmp_path / "Roaming")}
    )

    assert found == base / "7.3"


def _app(folder: Path, name: str, *, program: str, version: str | None = None) -> Path:
    """Create a macOS app bundle with one program and, if given, a version."""
    bundle = folder / f"{name}.app"
    executable = _touch(bundle / "Contents" / "MacOS" / program)
    info: dict[str, str] = {"CFBundleExecutable": program}
    if version is not None:
        info["CFBundleShortVersionString"] = version
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    return executable


@pytest.mark.usefixtures("macos")
def test_finds_mac_apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On macOS, apps in /Applications and ~/Applications are found, with their versions."""
    system = tmp_path / "Applications"
    monkeypatch.setattr(detection, "_MAC_APP_FOLDERS", (system,))
    home = tmp_path / "home"
    orca = _app(system, "OrcaSlicer", program="OrcaSlicer", version="2.5.2")
    beta = _app(home / "Applications", "OrcaSlicer 2.6 beta", program="OrcaSlicer", version="2.6.0")
    bambu = _app(system, "BambuStudio", program="BambuStudio", version="02.09.00.70")
    creality = _app(system, "Creality Print", program="CrealityPrint", version="7.3.0")

    found = find_installations("orca", home=home, environ={"PATH": ""})

    assert [(item.executable, item.version_text, item.prerelease) for item in found] == [
        (orca, "2.5.2", False),
        (beta, "2.6.0", True),
    ]
    bambu_found = find_installations("bambu_studio", home=home, environ={"PATH": ""})
    assert [(item.executable, item.version_text) for item in bambu_found] == [(bambu, "2.9.0.70")]
    assert [
        (item.executable, item.version_text)
        for item in find_installations("creality_print", home=home, environ={"PATH": ""})
    ] == [(creality, "7.3.0")]


@pytest.mark.usefixtures("macos")
def test_mac_app_without_info_plist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Info.plist, the only program inside is used and the version comes from the name."""
    monkeypatch.setattr(detection, "_MAC_APP_FOLDERS", (tmp_path,))
    program = _touch(tmp_path / "OrcaSlicer_V2.4.0.app" / "Contents" / "MacOS" / "OrcaSlicer")
    _touch(tmp_path / "OrcaSlicer_V2.3.0.app" / "Contents" / "Resources" / "readme")

    found = find_installations("orca", home=tmp_path / "home", environ={"PATH": ""})

    assert [(item.executable, item.version_text) for item in found] == [(program, "2.4.0")]


def test_mac_apps_are_ignored_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """App bundles are only looked for on macOS."""
    monkeypatch.setattr(detection, "_MAC_APP_FOLDERS", (tmp_path,))
    _app(tmp_path, "OrcaSlicer", program="OrcaSlicer", version="2.5.2")

    assert find_installations("orca", home=tmp_path / "home", environ={"PATH": ""}) == []


@pytest.mark.usefixtures("macos")
def test_mac_settings_folders(tmp_path: Path) -> None:
    """On macOS, settings are under ~/Library/Application Support, not XDG_CONFIG_HOME."""
    support = tmp_path / "Library" / "Application Support"
    environ = {"XDG_CONFIG_HOME": str(tmp_path / "config")}
    (tmp_path / "config" / "OrcaSlicer").mkdir(parents=True)
    assert find_data_directory("orca", home=tmp_path, environ=environ) is None

    (support / "OrcaSlicer").mkdir(parents=True)
    (support / "Creality" / "Creality Print" / "7.3").mkdir(parents=True)

    assert find_data_directory("orca", home=tmp_path, environ=environ) == support / "OrcaSlicer"
    assert find_data_directory("creality_print", home=tmp_path, environ=environ) == (
        support / "Creality" / "Creality Print" / "7.3"
    )
