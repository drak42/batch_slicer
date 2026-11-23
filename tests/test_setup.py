"""Tests for ``batchslicer setup``."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from batchslicer.cli.setup import SetupOptions, run_setup
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.core.config import Config, render_config
from conftest import set_home


def _answers(*values: str) -> Callable[[str], str]:
    """Return a read_line replacement that yields ``values`` in order."""
    iterator: Iterator[str] = iter(values)

    def read_line(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read_line


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a home folder with OrcaSlicer (two versions), Creality Print and an unopened Bambu Studio."""
    home = tmp_path / "home"
    for relative in (
        "Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage",
        "Downloads/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.3.1.AppImage",
        "Apps/CrealityPrint-V7.3.0.6157-x86_64-Release.AppImage",
        "Apps/BambuStudio_ubu24-v02.08.04.57-20260922.AppImage",
    ):
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    (home / ".config" / "OrcaSlicer").mkdir(parents=True)
    (home / ".config" / "Creality" / "Creality Print" / "7.3").mkdir(parents=True)
    set_home(monkeypatch, home)
    return home


def _environ(home: Path) -> dict[str, str]:
    """Return an environment with no PATH programs and default XDG folders."""
    return {"PATH": ""}


def test_no_prompt_writes_recommended_slicers(home: Path) -> None:
    """Without prompts, the recommended copy of each opened slicer is configured."""
    target = home / ".config" / "batchslicer" / "config.yaml"
    lines: list[str] = []

    run_setup(SetupOptions(config=target, no_prompt=True), write=lines.append, home=home, environ=_environ(home))

    config = Config(target)
    assert config.get("orca", "executable") == "~/Apps/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.0.AppImage"
    assert config.get("creality_print", "datadir") == "~/.config/Creality/Creality Print/7.3"
    assert config.get("bambu_studio", "executable") == ""
    assert any("Bambu Studio: found" in line and "not been opened" in line for line in lines)
    assert (home / "BatchSlicer" / "incoming").is_dir()
    assert (home / "BatchSlicer" / "output").is_dir()


def test_user_can_pick_another_version_or_skip_a_slicer(home: Path) -> None:
    """Interactively, Enter takes the recommendation, a number picks another, the last skips."""
    target = home / "config.yaml"

    run_setup(
        SetupOptions(config=target),
        read_line=_answers("2", "2"),
        write=lambda _: None,
        home=home,
        environ=_environ(home),
    )

    config = Config(target)
    assert config.get("orca", "executable").endswith("V2.3.1.AppImage")
    assert config.get("creality_print", "executable") == ""


def test_existing_config_needs_confirmation_and_is_backed_up(home: Path) -> None:
    """An existing file is only replaced after a yes, and the old one is kept."""
    target = home / "config.yaml"
    target.write_text("old: true\n")

    with pytest.raises(SlicerSelectionError, match="existing configuration was kept"):
        run_setup(SetupOptions(config=target), read_line=_answers(""), write=lambda _: None, home=home, environ=_environ(home))
    assert target.read_text() == "old: true\n"

    run_setup(SetupOptions(config=target), read_line=_answers("y", "", ""), write=lambda _: None, home=home, environ=_environ(home))
    assert (home / "config.yaml.bak").read_text() == "old: true\n"
    assert "orca:" in target.read_text()


def test_no_prompt_needs_force_to_replace(home: Path) -> None:
    """Unattended setup never replaces a configuration without --force."""
    target = home / "config.yaml"
    target.write_text("old: true\n")

    with pytest.raises(SlicerSelectionError, match="--force"):
        run_setup(SetupOptions(config=target, no_prompt=True), write=lambda _: None, home=home, environ=_environ(home))

    run_setup(SetupOptions(config=target, no_prompt=True, force=True), write=lambda _: None, home=home, environ=_environ(home))
    assert "orca:" in target.read_text()


def test_no_usable_slicer_is_explained(tmp_path: Path) -> None:
    """With nothing installed, setup stops and says what to do."""
    with pytest.raises(SlicerSelectionError, match="No usable slicer"):
        run_setup(
            SetupOptions(config=tmp_path / "config.yaml", no_prompt=True),
            write=lambda _: None,
            home=tmp_path,
            environ={"PATH": ""},
        )


def test_rendered_config_round_trips(tmp_path: Path) -> None:
    """The written file reads back to the same paths, with ~ for the home folder."""
    home = tmp_path / "home"
    text = render_config(
        {"orca": (home / "Apps" / "Orca.AppImage", Path('/opt/odd "name"/data'))},
        home=home,
    )
    (tmp_path / "config.yaml").write_text(text)
    config = Config(tmp_path / "config.yaml")

    assert config.get("orca", "executable") == "~/Apps/Orca.AppImage"
    assert config.get("orca", "datadir") == '/opt/odd "name"/data'
    assert config.get("creality_print", "executable") == ""
    assert config.get("paths", "output") == ""


def test_printers_are_kept_when_the_configuration_is_replaced(home: Path) -> None:
    """Setup rewrites the slicers but keeps the printers set up for --send."""
    target = home / "config.yaml"
    target.write_text('printers:\n  k2:\n    url: "http://192.168.1.50:7125"\n')
    lines: list[str] = []

    run_setup(SetupOptions(config=target, no_prompt=True, force=True), write=lines.append, home=home, environ=_environ(home))

    config = Config(target)
    config.load()
    assert config.section("printers") == {"k2": {"url": "http://192.168.1.50:7125"}}
    assert any("Kept the printers" in line for line in lines)


def test_new_configuration_shows_a_printers_example(tmp_path: Path) -> None:
    """Without printers the section is a commented example."""
    text = render_config({}, home=tmp_path)

    assert '#     url: "http://192.168.1.50:7125"' in text
    assert "\nprinters:" not in text
