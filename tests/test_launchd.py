"""Tests for running the watch folder as a launchd agent (macOS)."""

import plistlib
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from batchslicer.cli.service import ServiceOptions, run_service, system_manager
from batchslicer.infrastructure.launchd import Launchd, render_agent
from batchslicer.infrastructure.systemd import Systemd
from conftest import write_config

LABEL = "io.github.drak42.batchslicer.watch"


class FakeLaunchctl:
    """Stands in for launchctl: loading an agent "runs" it, writing its first line to its log."""

    def __init__(self, *, available: bool = True, first_line: str = "Watching /in for models; output to /out.",
                 exit_code: int = 0) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.available = available
        self.first_line = first_line
        self.exit_code = exit_code
        self.loaded: set[str] = set()

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = tuple(command)
        self.commands.append(command)
        if command[1] == "print" and command[2] == "gui/501":
            return subprocess.CompletedProcess(command, 0 if self.available else 113, "", "")
        if command[1] == "bootstrap":
            info = plistlib.loads(Path(command[3]).read_bytes())
            self.loaded.add(info["Label"])
            Path(info["StandardOutPath"]).write_text(self.first_line + "\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1] == "bootout":
            label = command[2].rpartition("/")[2]
            found = label in self.loaded
            self.loaded.discard(label)
            return subprocess.CompletedProcess(command, 0 if found else 3, "", "")
        if command[1] == "print":
            label = command[2].rpartition("/")[2]
            if label not in self.loaded:
                return subprocess.CompletedProcess(command, 113, "", "Could not find service")
            running = self.exit_code == 0
            text = (
                f"{command[2]} = {{\n\tactive count = 1\n"
                f"\tstate = {'running' if running else 'not running'}\n"
                f"\tlast exit code = {self.exit_code}\n\tevent triggers = {{\n\t\tstate = 0\n\t}}\n}}\n"
            )
            return subprocess.CompletedProcess(command, 0, text, "")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def mac_home(tmp_path: Path) -> Path:
    """A home folder and a BatchSlicer configuration with logs and cache inside ``tmp_path``."""
    write_config(tmp_path / "bs", {"paths": {"data": tmp_path / "cache", "logs": tmp_path / "logs"}})
    return tmp_path


def _install(home: Path, fake: FakeLaunchctl, lines: list[str], name: str | None = None) -> int:
    config = str(home / "bs" / "config.yaml")
    return run_service(
        ServiceOptions("install", name=name, run_arguments=("--config", config, "--profile", "k2 pla")),
        manager=Launchd(fake, home=home, uid=501), write=lines.append, sleep=lambda _: None,
        python="/py",
    )


def test_agent_starts_at_login_restarts_after_errors_and_logs_to_a_file(tmp_path: Path) -> None:
    """The property list runs the command at load, restarts it after an error, and logs to the file."""
    info = plistlib.loads(render_agent("watch", ["/py", "-m", "batchslicer", "--profile", "k2 pla"],
                                       tmp_path / "cache", tmp_path / "logs" / "service-watch.log"))

    assert info["Label"] == LABEL
    assert info["ProgramArguments"] == ["/py", "-m", "batchslicer", "--profile", "k2 pla"]
    assert info["RunAtLoad"] is True
    assert info["KeepAlive"] == {"SuccessfulExit": False}
    assert info["StandardOutPath"] == info["StandardErrorPath"] == str(tmp_path / "logs" / "service-watch.log")
    assert info["WorkingDirectory"] == str(tmp_path / "cache")


def test_install_loads_the_agent_and_reports(mac_home: Path) -> None:
    """install writes the agent, loads it into the user's session and shows its first output."""
    fake = FakeLaunchctl()
    lines: list[str] = []

    assert _install(mac_home, fake, lines) == 0

    plist = mac_home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert plist.is_file()
    assert ("launchctl", "bootstrap", "gui/501", str(plist)) in fake.commands
    assert "  | Watching /in for models; output to /out." in lines
    assert any(f'tail -f "{mac_home / "logs" / "service-watch.log"}"' in line for line in lines)
    [service] = Launchd(fake, home=mac_home, uid=501).installed()
    assert (service.name, service.path) == ("watch", plist)
    assert service.command[-4:] == ("--profile", "k2 pla", "--watch", "--no-prompt")


def test_a_failing_agent_is_reported(mac_home: Path) -> None:
    """An agent that stops with an error shows its output, and install fails."""
    fake = FakeLaunchctl(first_line="BatchSlicer startup failed: No profile named 'k2 pla'.", exit_code=1)
    lines: list[str] = []

    assert _install(mac_home, fake, lines) == 1
    assert "  | BatchSlicer startup failed: No profile named 'k2 pla'." in lines
    assert any("did not start watching (it is failed)" in line for line in lines)


def test_status_and_uninstall(mac_home: Path) -> None:
    """status shows the agent's state and log; uninstall unloads (stops) and removes it."""
    fake = FakeLaunchctl()
    _install(mac_home, fake, [])
    manager = Launchd(fake, home=mac_home, uid=501)
    lines: list[str] = []

    assert run_service(ServiceOptions("status"), manager=manager, write=lines.append) == 0
    assert "watch: active" in lines

    assert run_service(ServiceOptions("uninstall"), manager=manager, write=lines.append) == 0
    assert ("launchctl", "bootout", f"gui/501/{LABEL}") in fake.commands
    assert manager.installed() == []
    assert manager.state("watch") == "inactive"


def test_without_a_signed_in_session_the_terminal_is_suggested(mac_home: Path) -> None:
    """Over SSH without a desktop session, launchd cannot take agents: say what to do."""
    lines: list[str] = []
    status = run_service(ServiceOptions("status"), manager=Launchd(FakeLaunchctl(available=False), home=mac_home,
                                                                     uid=501), write=lines.append)
    assert status == 1
    assert "signed in at the Mac" in lines[0] and "Terminal window" in lines[0]


def test_each_system_gets_its_own_manager(request: pytest.FixtureRequest) -> None:
    """macOS uses launchd; Linux uses systemd."""
    assert isinstance(system_manager(), Systemd)
    request.getfixturevalue("macos")
    assert isinstance(system_manager(), Launchd)
