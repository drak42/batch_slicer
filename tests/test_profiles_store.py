"""Tests for saving and loading profiles."""

from pathlib import Path

import pytest
import yaml

from batchslicer.domain.profiles import LAST_RUN, Profile, is_valid_name
from batchslicer.infrastructure.profiles import ProfileError, ProfileStore


def _profile(name: str = "k2-petg", **choices: object) -> Profile:
    """Return a profile with typical choices."""
    values: dict[str, object] = {
        "slicer": "creality_print",
        "printer": "Creality K2 Plus 0.4 nozzle",
        "filament": "Generic PETG @Creality K2 Plus 0.4 nozzle",
        "process": "0.20mm Standard @Creality K2 Plus 0.4 nozzle",
    }
    values.update(choices)
    return Profile(name=name, **values)  # type: ignore[arg-type]


def test_missing_file_means_no_profiles(tmp_path: Path) -> None:
    """Before anything is saved there are no profiles."""
    assert ProfileStore(tmp_path / "profiles.yaml").load() == {}


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Saved profiles come back unchanged, including paths, and the folder is created."""
    store = ProfileStore(tmp_path / "nested" / "profiles.yaml")
    profile = _profile(input=tmp_path / "models", output=tmp_path / "out")

    store.save(profile)

    assert store.load() == {"k2-petg": profile}
    assert "k2-petg:" in (tmp_path / "nested" / "profiles.yaml").read_text()


def test_unset_choices_are_not_written(tmp_path: Path) -> None:
    """A profile holding only some choices stays small and loads with the rest unset."""
    store = ProfileStore(tmp_path / "profiles.yaml")

    store.save(Profile(name="orca-only", slicer="orca"))

    stored = yaml.safe_load((tmp_path / "profiles.yaml").read_text())
    assert stored == {"orca-only": {"slicer": "orca"}}
    assert store.get("orca-only") == Profile(name="orca-only", slicer="orca")


def test_names_match_ignoring_case_and_saving_replaces(tmp_path: Path) -> None:
    """Saving under a name that differs only in case replaces the old profile."""
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.save(_profile("K2-PETG"))
    store.save(_profile("k2-petg", process="0.12mm Fine"))

    assert list(store.load()) == ["k2-petg"]
    assert store.get("K2-petg").process == "0.12mm Fine"


def test_unknown_profile_lists_saved_ones(tmp_path: Path) -> None:
    """Asking for a missing profile names the ones that exist."""
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.save(_profile("k2-petg"))
    store.save(_profile(LAST_RUN))

    with pytest.raises(ProfileError, match=r"No profile named 'ender' \(saved profiles: k2-petg, last\)"):
        store.get("ender")


def test_delete(tmp_path: Path) -> None:
    """Deleting removes only that profile and returns it."""
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.save(_profile("a"))
    store.save(_profile("b"))

    assert store.delete("A").name == "a"
    assert list(store.load()) == ["b"]
    with pytest.raises(ProfileError):
        store.delete("a")


@pytest.mark.parametrize("name", ["", " leading", "a/b", "x" * 65, "-dash-first"])
def test_invalid_names_are_refused(tmp_path: Path, name: str) -> None:
    """Names must be simple so they are easy to type and safe in YAML."""
    assert not is_valid_name(name)
    with pytest.raises(ProfileError, match="Invalid profile name"):
        ProfileStore(tmp_path / "profiles.yaml").save(Profile(name=name))


def test_hand_edited_file_is_validated(tmp_path: Path) -> None:
    """Typos and malformed entries in a hand-edited file are reported clearly."""
    path = tmp_path / "profiles.yaml"
    path.write_text("k2:\n  printr: X\n")
    with pytest.raises(ProfileError, match="unknown settings: printr"):
        ProfileStore(path).load()

    path.write_text("- not a mapping\n")
    with pytest.raises(ProfileError, match="not a mapping"):
        ProfileStore(path).load()

    path.write_text("k2: [\n")
    with pytest.raises(ProfileError, match="Cannot read profiles"):
        ProfileStore(path).load()


def test_paths_in_a_hand_edited_file_may_use_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """input and output written with ~ point into the home folder."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    path = tmp_path / "profiles.yaml"
    path.write_text("nightly:\n  input: ~/BatchSlicer/incoming\n")

    assert ProfileStore(path).get("nightly").input == tmp_path / "home" / "BatchSlicer" / "incoming"


def test_summary_describes_the_choices() -> None:
    """The summary lists what the profile sets."""
    assert _profile(output=Path("/out")).summary() == (
        "creality_print, Creality K2 Plus 0.4 nozzle, Generic PETG @Creality K2 Plus 0.4 nozzle, "
        "0.20mm Standard @Creality K2 Plus 0.4 nozzle, output /out"
    )
    assert Profile(name="empty").summary() == "no choices saved"
