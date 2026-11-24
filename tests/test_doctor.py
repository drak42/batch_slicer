"""Tests for ``batchslicer doctor``."""

import json
from pathlib import Path

import pytest
import yaml

from batchslicer.cli.doctor import DoctorOptions, run_doctor
from conftest import FakeMoonraker, FakeOctoPrint, fake_program, write_config

HELP_TEXT = "Usage: slicer [ OPTIONS ]\n --slice option   Slice the plates\n"


def _program(path: Path, *, output: str = HELP_TEXT, exit_code: int = 0) -> Path:
    """Write a fake slicer program that prints ``output`` (a ``.cmd`` file on Windows)."""
    return fake_program(path, output, exit_code=exit_code)


def _creality_data(path: Path, *, printers: list[str]) -> Path:
    """Write a minimal Creality Print settings folder where ``printers`` were added.

    The built-in presets always include a K2 Plus; only the added printers are offered.
    """
    machines = path / "system" / "Creality" / "machine"
    machines.mkdir(parents=True)
    for name in {"K2 Plus", *printers}:
        (machines / f"{name}.json").write_text(json.dumps({"name": name, "instantiation": "true"}))
    (path / "Creality.conf").write_text(
        json.dumps({"orca_presets": [{"machine": name} for name in printers]})
    )
    return path


def _report(options: DoctorOptions) -> tuple[int, list[str]]:
    """Run the doctor and return the problem count and the report lines."""
    lines: list[str] = []
    return run_doctor(options, write=lines.append), lines


def test_healthy_setup_reports_no_problems(tmp_path: Path) -> None:
    """A working slicer with printers gives a clean report."""
    config = write_config(
        tmp_path / "settings",
        {
            "creality_print": {
                "executable": _program(tmp_path / "bin" / "creality"),
                "datadir": _creality_data(tmp_path / "creality", printers=["K2 Plus"]),
            },
            "paths": {"profiles": tmp_path / "profiles.yaml"},
        },
    )

    problems, lines = _report(DoctorOptions(config=config.path))

    assert problems == 0
    assert lines[0].startswith("BatchSlicer v")
    assert f"  {config.path} (from --config)" in lines
    assert any(line.strip().startswith("runs:     yes") for line in lines)
    assert "    presets:  1 printer" in lines
    assert "  OrcaSlicer: not configured" in lines
    assert "  0 saved (none saved yet)" in lines
    assert lines[-1] == "No problems found."


def test_missing_configuration_is_a_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a configuration, the report says how to create one."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("BATCHSLICER_CONFIG", raising=False)

    problems, lines = _report(DoctorOptions())

    assert problems == 1
    assert any("batchslicer setup" in line for line in lines if line.startswith("  PROBLEM"))
    assert "Folders:" in lines


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("missing-program", "Creality Print program not found"),
        ("missing-settings", "Creality Print settings folder not found"),
        ("program-fails", "did not run its command-line help (exit code 3): crashed"),
        ("no-printers", "Creality Print offers no printers"),
    ],
)
def test_slicer_problems_are_named(tmp_path: Path, setup: str, expected: str) -> None:
    """Each kind of slicer problem is reported with what is wrong."""
    program = tmp_path / "bin" / "creality"
    if setup != "missing-program":
        if setup == "program-fails":
            program = fake_program(program, stderr="crashed\n", exit_code=3)
        else:
            program = _program(program)
    data = tmp_path / "creality"
    if setup != "missing-settings":
        _creality_data(data, printers=[] if setup == "no-printers" else ["K2 Plus"])
    config = write_config(
        tmp_path / "settings",
        {"creality_print": {"executable": program, "datadir": data}},
    )

    problems, lines = _report(DoctorOptions(config=config.path))

    assert problems == 1
    assert any(expected in line for line in lines), lines


def test_nothing_configured_is_a_problem(tmp_path: Path) -> None:
    """A configuration with no slicer set up cannot slice anything."""
    config = write_config(tmp_path, {"orca": {"executable": "", "datadir": ""}})

    problems, lines = _report(DoctorOptions(config=config.path))

    assert problems == 1
    assert any("No slicer is configured" in line for line in lines)


def test_unreadable_profiles_are_a_problem(tmp_path: Path) -> None:
    """A hand-edited profiles file with a mistake is reported."""
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text("bad:\n  printr: x\n")
    config = write_config(
        tmp_path / "settings",
        {
            "creality_print": {
                "executable": _program(tmp_path / "bin" / "creality"),
                "datadir": _creality_data(tmp_path / "creality", printers=["K2 Plus"]),
            },
            "paths": {"profiles": profiles},
        },
    )

    problems, lines = _report(DoctorOptions(config=config.path))

    assert problems == 1
    assert any("unknown settings: printr" in line for line in lines)


def test_printers_are_checked(
    tmp_path: Path, fake_moonraker: FakeMoonraker, fake_octoprint: FakeOctoPrint
) -> None:
    """A printer that answers is shown with its state; one that refuses is a problem."""
    fake_moonraker.api_key = "secret"
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({
            "creality_print": {
                "executable": str(_program(tmp_path / "bin" / "creality")),
                "datadir": str(_creality_data(tmp_path / "creality", printers=["K2 Plus"])),
            },
            "printers": {
                "k2": {"url": fake_moonraker.url, "api_key": "secret"},
                "spare": {"url": fake_moonraker.url},
                "ender": {"type": "octoprint", "url": fake_octoprint.url, "api_key": fake_octoprint.api_key},
            },
        })
    )

    problems, lines = _report(DoctorOptions(config=path))

    assert problems == 1
    assert any(f"k2 ({fake_moonraker.url}): answers, Klipper is ready, Moonraker v0.9.3" in line for line in lines)
    assert any("PROBLEM: spare" in line and "refused access" in line for line in lines)
    assert not any("loaded filaments" in line for line in lines)  # no CFS on this stand-in
    assert any(
        f"ender (OctoPrint, {fake_octoprint.url}): answers, printer is Operational, OctoPrint 1.10.3"
        in line
        for line in lines
    )


def test_loaded_cfs_filaments_are_listed(tmp_path: Path, fake_moonraker: FakeMoonraker) -> None:
    """A printer with a CFS shows what is loaded in each slot."""
    from test_filaments import K2_STATUS

    fake_moonraker.objects = K2_STATUS
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({
            "creality_print": {
                "executable": str(_program(tmp_path / "bin" / "creality")),
                "datadir": str(_creality_data(tmp_path / "creality", printers=["K2 Plus"])),
            },
            "printers": {"k2": {"url": fake_moonraker.url}},
        })
    )

    _, lines = _report(DoctorOptions(config=path))

    start = lines.index("    loaded filaments (for --loaded-filaments):")
    assert lines[start + 1 : start + 4] == [
        "      CFS 1B dark blue PETG  (#1B04AE)",
        "      CFS 1C light grey PETG  (#9EA7AE)",
        "      external spool white PETG  (#FFFFFF)",
    ]


@pytest.mark.parametrize(("on_windows", "problems"), [(True, 0), (False, 1)])
def test_missing_help_text_is_fine_only_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, on_windows: bool, problems: int
) -> None:
    """Windows slicers run their help without showing it; elsewhere that means trouble."""
    monkeypatch.setattr("batchslicer.core.locations.is_windows", lambda: on_windows)
    data = tmp_path / "creality"
    _creality_data(data, printers=["K2 Plus"])
    config = write_config(
        tmp_path / "settings",
        # What Creality Print 7.3 prints on Windows instead of its help.
        {"creality_print": {
            "executable": fake_program(tmp_path / "bin" / "creality", "System OpenGL library released\n"),
            "datadir": data,
        }},
    )

    found, lines = _report(DoctorOptions(config=config.path))

    assert found == problems, lines
    if on_windows:
        assert any("Windows shows no command-line help" in line for line in lines), lines
