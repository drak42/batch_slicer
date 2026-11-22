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
    return Profile.single(name, **values)  # type: ignore[arg-type]


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

    store.save(Profile.single("orca-only", slicer="orca"))

    stored = yaml.safe_load((tmp_path / "profiles.yaml").read_text())
    assert stored == {"orca-only": {"slicer": "orca"}}
    assert store.get("orca-only") == Profile.single("orca-only", slicer="orca")


def test_names_match_ignoring_case_and_saving_replaces(tmp_path: Path) -> None:
    """Saving under a name that differs only in case replaces the old profile."""
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.save(_profile("K2-PETG"))
    store.save(_profile("k2-petg", process="0.12mm Fine"))

    assert list(store.load()) == ["k2-petg"]
    assert store.get("K2-petg").targets[0].process == "0.12mm Fine"


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


def test_multi_printer_profile_round_trip(tmp_path: Path) -> None:
    """A profile with several targets is stored as a 'targets' list and read back."""
    from batchslicer.domain.profiles import Target

    store = ProfileStore(tmp_path / "profiles.yaml")
    profile = Profile(
        name="both",
        targets=(
            Target(slicer="creality_print", printer="K2 Plus", filament="PETG", process="Fine"),
            Target(slicer="orca", printer="Ender", filament="PLA", process="Draft"),
        ),
        input=tmp_path / "models",
    )

    store.save(profile)

    stored = yaml.safe_load((tmp_path / "profiles.yaml").read_text())
    assert stored == {
        "both": {
            "targets": [
                {"slicer": "creality_print", "printer": "K2 Plus", "filament": "PETG", "process": "Fine"},
                {"slicer": "orca", "printer": "Ender", "filament": "PLA", "process": "Draft"},
            ],
            "input": str(tmp_path / "models"),
        }
    }
    assert store.get("both") == profile
    assert profile.summary() == f"2 printers: K2 Plus; Ender, input {tmp_path / 'models'}"


def test_single_printer_profiles_keep_the_flat_format(tmp_path: Path) -> None:
    """Profiles saved before multi-printer support still load unchanged."""
    path = tmp_path / "profiles.yaml"
    path.write_text("k2:\n  slicer: creality_print\n  printer: K2 Plus\n  output: /out\n")

    profile = ProfileStore(path).get("k2")

    assert not profile.is_multi
    assert profile.targets[0].printer == "K2 Plus"
    assert profile.output == Path("/out")


def test_malformed_targets_are_reported(tmp_path: Path) -> None:
    """Mixing flat choices with a targets list, or a bad list, is explained."""
    path = tmp_path / "profiles.yaml"
    path.write_text("x:\n  printer: A\n  targets:\n    - printer: B\n")
    with pytest.raises(ProfileError, match="sets both 'targets'"):
        ProfileStore(path).load()

    path.write_text("x:\n  targets: []\n")
    with pytest.raises(ProfileError, match="must be a list"):
        ProfileStore(path).load()

    path.write_text("x:\n  targets:\n    - printr: A\n")
    with pytest.raises(ProfileError, match="unknown target settings: printr"):
        ProfileStore(path).load()


def test_combine_merges_targets_and_takes_the_first_input() -> None:
    """Combining profiles keeps every printer; input and output come from the first that sets them."""
    from batchslicer.domain.profiles import combine

    first = Profile.single("a", slicer="orca", printer="Ender")
    second = Profile.single("b", slicer="creality_print", printer="K2", input=Path("/m"), output=Path("/o"))
    third = Profile.single("c", slicer="orca", printer="X", input=Path("/other"))

    combined = combine("run", [first, second, third])

    assert [target.printer for target in combined.targets] == ["Ender", "K2", "X"]
    assert combined.input == Path("/m")
    assert combined.output == Path("/o")


def test_summary_names_the_slicer_when_a_printer_repeats() -> None:
    """The same printer with two slicers is told apart in the summary."""
    from batchslicer.domain.profiles import combine

    both = combine(
        "run",
        [
            Profile.single("a", slicer="creality_print", printer="K2"),
            Profile.single("b", slicer="orca", printer="K2"),
            Profile.single("c", slicer="orca", printer="Ender"),
        ],
    )

    assert both.summary() == "3 printers: K2 (creality_print); K2 (orca); Ender"


def test_slicing_settings_round_trip(tmp_path: Path) -> None:
    """orient, allow_newer_files and jobs are saved, loaded and summarised."""
    store = ProfileStore(tmp_path / "profiles.yaml")
    profile = Profile.single("farm", slicer="orca", printer="K2")
    store.save(Profile(
        name=profile.name,
        targets=profile.targets,
        orient="retry",
        allow_newer_files=True,
        jobs=3,
    ))

    loaded = store.get("farm")

    assert (loaded.orient, loaded.allow_newer_files, loaded.jobs) == ("retry", True, 3)
    assert "orient retry, newer files allowed, 3 jobs" in loaded.summary()
    stored = yaml.safe_load((tmp_path / "profiles.yaml").read_text(encoding="utf-8"))
    assert stored["farm"] == {
        "slicer": "orca",
        "printer": "K2",
        "orient": "retry",
        "allow_newer_files": True,
        "jobs": 3,
    }


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("orient: upside-down", "unknown orient mode"),
        ("allow_newer_files: maybe", "true or false"),
        ("jobs: 0", "whole number"),
        ("jobs: yes", "whole number"),
    ],
)
def test_bad_slicing_settings_are_reported(tmp_path: Path, setting: str, message: str) -> None:
    """Hand-edited settings are checked when loaded."""
    path = tmp_path / "profiles.yaml"
    path.write_text(f"farm:\n  slicer: orca\n  {setting}\n", encoding="utf-8")

    with pytest.raises(ProfileError, match=message):
        ProfileStore(path).load()
