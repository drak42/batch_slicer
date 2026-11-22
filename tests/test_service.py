"""Tests for running the watch folder as a systemd user service."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from batchslicer.cli.arguments import parse_arguments
from batchslicer.cli.service import ServiceOptions, absolute_paths, run_service, service_command
from batchslicer.infrastructure.systemd import (
    Systemd,
    installed_services,
    quote,
    render_unit,
    unquote_command,
)
from conftest import write_config


class FakeSystemctl:
    """Stands in for systemctl, journalctl and loginctl, recording what is run."""

    def __init__(self, *, available: bool = True, log: Sequence[str] = ("Watching /in for models; output to /out.",),
                 state: str = "active", linger: str = "Linger=no") -> None:
        self.commands: list[tuple[str, ...]] = []
        self.available = available
        self.log = list(log)
        self.state = state
        self.linger = linger

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = tuple(command)
        self.commands.append(command)
        if not self.available:
            return subprocess.CompletedProcess(command, 127, "", "systemctl not found")
        if command[:3] == ("systemctl", "--user", "is-active"):
            return subprocess.CompletedProcess(command, 0, self.state + "\n", "")
        if command[0] == "journalctl":
            return subprocess.CompletedProcess(command, 0, "\n".join(self.log) + "\n", "")
        if command[0] == "loginctl":
            return subprocess.CompletedProcess(command, 0, self.linger + "\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def setup_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the user's config folder at ``tmp_path`` and write a BatchSlicer configuration."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("USER", "maker")
    write_config(tmp_path / "bs", {"paths": {"data": tmp_path / "cache"}})
    return tmp_path


@pytest.mark.parametrize(
    "argument",
    ["plain", "Creality K2 Plus 0.4 nozzle", 'say "hi"', "50%", "$HOME", "back\\slash", "it's", ""],
)
def test_arguments_survive_quoting(argument: str) -> None:
    """Whatever an argument holds, the ExecStart line gives it back unchanged."""
    assert unquote_command(" ".join([quote("python"), quote(argument), quote("--watch")])) == (
        "python", argument, "--watch",
    )


def test_unit_stops_like_ctrl_c_and_starts_at_login(tmp_path: Path) -> None:
    """The unit runs the command, stops with SIGINT and restarts after a crash."""
    text = render_unit("watch", ["/venv/bin/python", "-m", "batchslicer", "--profile", "k2 pla"], tmp_path)

    assert 'ExecStart=/venv/bin/python -m batchslicer --profile "k2 pla"' in text
    assert "KillSignal=SIGINT" in text
    assert "Restart=on-failure" in text
    assert "WantedBy=default.target" in text
    assert f"WorkingDirectory={tmp_path}" in text


def test_paths_become_absolute_and_the_config_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--input/--output/--config are made absolute; the config is added; --watch is not doubled."""
    monkeypatch.chdir(tmp_path)
    assert absolute_paths(["--input", "drop", "--output=out", "--send", "k2"]) == [
        "--input", str(tmp_path / "drop"), f"--output={tmp_path / 'out'}", "--send", "k2",
    ]
    command = service_command(["--profile", "k2", "--watch"], Path("conf/config.yaml"), "/py")
    assert command == [
        "/py", "-m", "batchslicer", "--config", str(tmp_path / "conf" / "config.yaml"),
        "--profile", "k2", "--watch", "--no-prompt",
    ]


def test_install_writes_starts_and_reports(setup_home: Path) -> None:
    """install writes the unit, enables and restarts it, and shows its first output."""
    fake = FakeSystemctl()
    lines: list[str] = []
    config = setup_home / "bs" / "config.yaml"

    status = run_service(
        ServiceOptions("install", run_arguments=("--config", str(config), "--profile", "k2 pla")),
        systemd=Systemd(fake), write=lines.append, sleep=lambda _: None, python="/venv/bin/python",
    )

    assert status == 0
    unit = setup_home / "config" / "systemd" / "user" / "batchslicer-watch.service"
    [service] = installed_services()
    assert service.path == unit
    assert service.command == (
        "/venv/bin/python", "-m", "batchslicer", "--config", str(config), "--profile", "k2 pla",
        "--watch", "--no-prompt",
    )
    assert f"WorkingDirectory={setup_home / 'cache'}" in unit.read_text()
    assert ("systemctl", "--user", "daemon-reload") in fake.commands
    assert ("systemctl", "--user", "enable", "batchslicer-watch.service") in fake.commands
    assert ("systemctl", "--user", "restart", "batchslicer-watch.service") in fake.commands
    assert "  | Watching /in for models; output to /out." in lines
    assert any("loginctl enable-linger" in line for line in lines)


def test_a_service_that_does_not_start_watching_is_reported(setup_home: Path) -> None:
    """When the service stops at once, its output is shown and install fails."""
    fake = FakeSystemctl(state="failed", log=["BatchSlicer startup failed: No profile named 'k3'."])
    lines: list[str] = []

    status = run_service(
        ServiceOptions("install", name="k3", run_arguments=("--config", str(setup_home / "bs" / "config.yaml"),
                                                            "--profile", "k3")),
        systemd=Systemd(fake), write=lines.append, sleep=lambda _: None, python="/py",
    )

    assert status == 1
    assert "  | BatchSlicer startup failed: No profile named 'k3'." in lines
    assert any("did not start watching (it is failed)" in line for line in lines)


def test_status_and_uninstall(setup_home: Path) -> None:
    """status shows each service's state and command; uninstall stops and removes it."""
    fake = FakeSystemctl(linger="Linger=yes")
    config = str(setup_home / "bs" / "config.yaml")
    for name in ("k2", "ender"):
        run_service(ServiceOptions("install", name=name, run_arguments=("--config", config, "--profile", name)),
                    systemd=Systemd(fake), write=lambda _: None, sleep=lambda _: None, python="/py")
    lines: list[str] = []

    assert run_service(ServiceOptions("status"), systemd=Systemd(fake), write=lines.append) == 0
    assert "ender: active" in lines and "k2: active" in lines
    assert f"  runs: batchslicer --config {config} --profile k2 --watch --no-prompt" in lines

    assert run_service(ServiceOptions("uninstall", name="k2"), systemd=Systemd(fake), write=lines.append) == 0
    assert ("systemctl", "--user", "disable", "--now", "batchslicer-k2.service") in fake.commands
    assert [service.name for service in installed_services()] == ["ender"]

    lines.clear()
    assert run_service(ServiceOptions("uninstall", name="k2"), systemd=Systemd(fake), write=lines.append) == 1
    assert lines == ["BatchSlicer service uninstall failed: No service named 'k2' (installed: ender)."]


def test_status_with_nothing_installed(setup_home: Path) -> None:
    """With no services, status says how to add one."""
    lines: list[str] = []
    assert run_service(ServiceOptions("status"), systemd=Systemd(FakeSystemctl()), write=lines.append) == 0
    assert "No BatchSlicer services are installed" in lines[0]


def test_without_systemd_the_terminal_is_suggested(setup_home: Path) -> None:
    """Where systemctl --user does not work, nothing is written and tmux/screen are suggested."""
    lines: list[str] = []
    status = run_service(ServiceOptions("status"), systemd=Systemd(FakeSystemctl(available=False)),
                         write=lines.append)
    assert status == 1
    assert "tmux or screen" in lines[0]


def test_bad_service_names_are_refused(setup_home: Path) -> None:
    """Names must fit in a unit name."""
    lines: list[str] = []
    status = run_service(ServiceOptions("uninstall", name="../etc"), systemd=Systemd(FakeSystemctl()),
                         write=lines.append)
    assert status == 1
    assert "cannot be a service name" in lines[0]


def test_service_command_line() -> None:
    """--name is taken out; the rest are run options, checked as a watch run."""
    options = parse_arguments(["service", "install", "--name", "k2", "--profile", "k2 pla", "--input", "drop"])
    assert options == ServiceOptions("install", name="k2", run_arguments=("--profile", "k2 pla", "--input", "drop"))
    assert parse_arguments(["service", "status"]) == ServiceOptions("status")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["service", "install", "--input", "drop"], "install needs --profile NAME"),
        (["service", "install", "--profile", "k2", "--start"], "--start cannot be used with --watch"),
        (["service", "status", "--profile", "k2"], "'status' takes only --name"),
        (["service", "restart"], "invalid choice"),
    ],
)
def test_service_command_line_mistakes(arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Mistakes stop with exit status 2 and say what is wrong."""
    with pytest.raises(SystemExit) as stopped:
        parse_arguments(arguments)
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err
