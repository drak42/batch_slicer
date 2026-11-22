"""Tests for locating a slicer's built-in presets."""

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.backends.presets import PresetError
from batchslicer.backends.profiles import find_system_profiles, is_appimage
from test_opc import make_opc


def _fake_appimage(path: Path) -> Path:
    """Write a file with the AppImage type 2 signature."""
    path.write_bytes(b"\x7fELF\x02\x01\x01\x00AI\x02" + b"\x00" * 32)
    return path


def _data_directory(tmp_path: Path, *vendors: str) -> Path:
    """Create a data directory whose system folder only has packed .opc files."""
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    for vendor in vendors:
        (data / "system" / f"{vendor}.opc").write_bytes(b"ZCRO")
    return data


def _extracting_run(calls: list[tuple[str, ...]], *, skip: str = "") -> Mock:
    """Return a subprocess.run stand-in that extracts like an AppImage would."""

    def run(command: tuple[str, ...], *, cwd: str, **kwargs: object) -> Mock:
        calls.append(command)
        vendor = command[2].split("/")[-1].rstrip("*")
        if vendor != skip:
            folder = Path(cwd) / "squashfs-root" / "resources" / "profiles" / vendor / "machine"
            folder.mkdir(parents=True)
            (folder / "printer.json").write_text('{"name": "P"}')
        return Mock(returncode=0)

    return Mock(side_effect=run)


def test_is_appimage_checks_the_signature(tmp_path: Path) -> None:
    """Only files with the AppImage signature count, whatever their name."""
    assert is_appimage(_fake_appimage(tmp_path / "Orca"))
    plain = tmp_path / "plain.AppImage"
    plain.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00")
    assert not is_appimage(plain)
    assert not is_appimage(tmp_path / "missing")


def test_json_presets_in_the_data_directory_are_used_directly(tmp_path: Path) -> None:
    """Creality Print style data directories need no extraction."""
    data = tmp_path / "data"
    (data / "system" / "Creality" / "machine").mkdir(parents=True)
    (data / "system" / "Creality" / "machine" / "k2.json").write_text("{}")

    assert find_system_profiles(tmp_path / "exe", data, tmp_path / "cache") == data / "system"


def test_packed_presets_are_extracted_from_the_appimage_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each vendor's presets are extracted once and the cache is reused."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _data_directory(tmp_path, "Creality", "OrcaFilamentLibrary")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("batchslicer.backends.profiles.subprocess.run", _extracting_run(calls))

    first = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())
    second = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert first == second
    assert first.parent == tmp_path / "cache"
    assert (first / "Creality" / "machine" / "printer.json").is_file()
    assert (first / "OrcaFilamentLibrary").is_dir()
    assert calls == [
        (str(executable), "--appimage-extract", "resources/profiles/Creality*"),
        (str(executable), "--appimage-extract", "resources/profiles/OrcaFilamentLibrary*"),
    ]
    assert not list((tmp_path / "cache").glob("extract-*"))


def test_new_vendor_triggers_a_fresh_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vendor added in the slicer after the first extraction is picked up."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _data_directory(tmp_path, "Creality")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr("batchslicer.backends.profiles.subprocess.run", _extracting_run(calls))
    find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())
    (data / "system" / "Prusa.opc").write_bytes(b"ZCRO")

    target = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert (target / "Prusa").is_dir()
    assert len(calls) == 3


def test_missing_vendor_in_the_appimage_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the program does not contain a vendor's presets, the error says which."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _data_directory(tmp_path, "Creality", "Mystery")
    monkeypatch.setattr(
        "batchslicer.backends.profiles.subprocess.run", _extracting_run([], skip="Mystery")
    )

    with pytest.raises(PresetError, match="Mystery"):
        find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())


def test_failed_extraction_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing or hanging extraction becomes a PresetError."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _data_directory(tmp_path, "Creality")
    monkeypatch.setattr(
        "batchslicer.backends.profiles.subprocess.run",
        Mock(side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)),
    )

    with pytest.raises(PresetError, match="Could not extract"):
        find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())


def test_installed_profiles_next_to_the_program_are_used(tmp_path: Path) -> None:
    """A non-AppImage install with resources/profiles needs no extraction."""
    install = tmp_path / "orca"
    (install / "bin").mkdir(parents=True)
    executable = install / "bin" / "orca-slicer"
    executable.write_text("")
    profiles = install / "resources" / "profiles"
    (profiles / "Creality" / "machine").mkdir(parents=True)
    (profiles / "Creality" / "machine" / "k2.json").write_text("{}")

    found = find_system_profiles(executable, _data_directory(tmp_path, "Creality"), tmp_path / "cache")

    assert found == profiles


def test_presets_inside_a_mac_app_are_used(tmp_path: Path) -> None:
    """A macOS app keeps its presets in Contents/Resources/profiles."""
    contents = tmp_path / "OrcaSlicer.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    executable = contents / "MacOS" / "OrcaSlicer"
    executable.write_text("")
    profiles = contents / "Resources" / "profiles"
    (profiles / "Creality" / "machine").mkdir(parents=True)
    (profiles / "Creality" / "machine" / "k2.json").write_text("{}")

    found = find_system_profiles(executable, _data_directory(tmp_path, "Creality"), tmp_path / "cache")

    assert found in (profiles, contents / "resources" / "profiles")  # same on a case-insensitive disk


def test_no_presets_anywhere_is_reported(tmp_path: Path) -> None:
    """Without JSON presets, .opc files or a usable program, PresetError explains why."""
    with pytest.raises(PresetError, match="No built-in presets"):
        find_system_profiles(tmp_path / "exe", tmp_path / "empty", tmp_path / "cache")

    plain = tmp_path / "orca-slicer"
    plain.write_text("")
    with pytest.raises(PresetError, match="Creality.opc is not an OrcaSlicer preset file"):
        find_system_profiles(plain, _data_directory(tmp_path, "Creality"), tmp_path / "cache")


def _bundling_opc_run(calls: list[tuple[str, ...]], *, bundled: set[str]) -> Mock:
    """Return a subprocess.run stand-in for an AppImage that ships .opc files (OrcaSlicer 2.5)."""

    def run(command: tuple[str, ...], *, cwd: str, **kwargs: object) -> Mock:
        calls.append(command)
        vendor = command[2].split("/")[-1].rstrip("*")
        profiles = Path(cwd) / "squashfs-root" / "resources" / "profiles"
        if vendor in bundled:
            (profiles / vendor).mkdir(parents=True)
            (profiles / vendor / "cover.png").write_bytes(b"png")  # images only, no JSON
            make_opc(profiles / f"{vendor}.opc", vendor=vendor)
        return Mock(returncode=0)

    return Mock(side_effect=run)


def _real_opc_data_directory(tmp_path: Path, *vendors: str) -> Path:
    """Create a data directory whose system folder has real (small) .opc files."""
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    for vendor in vendors:
        make_opc(data / "system" / f"{vendor}.opc", vendor=vendor)
    return data


def test_opc_files_shipped_in_the_appimage_are_unpacked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OrcaSlicer 2.5 ships .opc files; they are unpacked to JSON in the cache."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _data_directory(tmp_path, "Acme")
    monkeypatch.setattr(
        "batchslicer.backends.profiles.subprocess.run", _bundling_opc_run([], bundled={"Acme"})
    )

    found = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert (found / "Acme" / "machine" / "Acme One 0.4 nozzle.json").is_file()
    assert not (found / "Acme" / "cover.png").exists()


def test_vendors_the_program_lacks_come_from_the_settings_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vendor not shipped with the program is unpacked from the settings folder's .opc."""
    executable = _fake_appimage(tmp_path / "OrcaSlicer.AppImage")
    data = _real_opc_data_directory(tmp_path, "Acme", "Custom")
    monkeypatch.setattr(
        "batchslicer.backends.profiles.subprocess.run", _bundling_opc_run([], bundled={"Acme"})
    )

    found = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert (found / "Custom" / "process" / "0.20mm Standard @Acme.json").is_file()


def test_installs_without_bundled_presets_use_the_settings_folder(tmp_path: Path) -> None:
    """A program that is not an AppImage and ships no JSON uses the settings folder's .opc files."""
    executable = tmp_path / "orca-slicer"
    executable.write_text("")
    data = _real_opc_data_directory(tmp_path, "Acme")

    found = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert (found / "Acme" / "filament" / "Acme PLA.json").is_file()


def test_changed_opc_files_rebuild_the_cache(tmp_path: Path) -> None:
    """When the slicer updates its .opc files, the presets are unpacked again."""
    executable = tmp_path / "orca-slicer"
    executable.write_text("")
    data = _real_opc_data_directory(tmp_path, "Acme")
    first = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    make_opc(data / "system" / "Acme.opc", vendor="Acme")
    opc = data / "system" / "Acme.opc"
    stat = opc.stat()
    os.utime(opc, (stat.st_atime, stat.st_mtime + 60))
    second = find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())

    assert first != second
    assert first.exists() and second.exists()


def test_opc_holding_another_vendor_is_refused(tmp_path: Path) -> None:
    """A settings-folder .opc file named for one vendor but holding another is refused."""
    executable = tmp_path / "orca-slicer"
    executable.write_text("")
    data = tmp_path / "data"
    (data / "system").mkdir(parents=True)
    make_opc(data / "system" / "Acme.opc", vendor="Other")

    with pytest.raises(PresetError, match="holds presets for 'Other'"):
        find_system_profiles(executable, data, tmp_path / "cache", logger=Mock())
