"""Tests for running the watch folder as a Windows scheduled task, and its service host."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from batchslicer.cli import service_host
from batchslicer.cli.service import ServiceOptions, run_service, system_manager
from batchslicer.infrastructure.windows_tasks import WindowsTasks, host_command, render_task
from conftest import write_config


class FakeTaskScheduler:
    """Stands in for schtasks and PowerShell's Get-ScheduledTask.

    A started task writes its first line to its log; once its stop file
    appears it stops cleanly, unless ``ignores_stop`` (then only /End stops it).
    """

    def __init__(self, folder: Path, *, first_line: str = "Watching C:/in for models; output to C:/out.",
                 exit_code: int = 0, ignores_stop: bool = False, available: bool = True) -> None:
        self.folder = folder
        self.first_line = first_line
        self.exit_code = exit_code
        self.ignores_stop = ignores_stop
        self.available = available
        self.commands: list[tuple[str, ...]] = []
        self.tasks: dict[str, str] = {}
        self.xml: dict[str, str] = {}
        self.last_result: dict[str, int] = {}

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = tuple(command)
        self.commands.append(command)
        ok = subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ("schtasks", "/Query"):
            return ok if self.available else subprocess.CompletedProcess(command, 1, "", "denied")
        if command[:2] == ("schtasks", "/Create"):
            name = command[3].rpartition("\\")[2]
            self.xml[name] = Path(command[5]).read_text(encoding="utf-16")
            self.tasks[name] = "Ready"
            self.last_result[name] = 267011
            return ok
        if command[:2] == ("schtasks", "/Run"):
            name = command[3].rpartition("\\")[2]
            record = json.loads((self.folder / f"{name}.json").read_text(encoding="utf-8"))
            Path(record["log_file"]).write_text(self.first_line + "\n", encoding="utf-8")
            self.tasks[name] = "Running" if self.exit_code == 0 else "Ready"
            self.last_result[name] = 267009 if self.exit_code == 0 else self.exit_code
            return ok
        if command[:2] == ("schtasks", "/End"):
            self.tasks[command[3].rpartition("\\")[2]] = "Ready"
            return ok
        if command[:2] == ("schtasks", "/Delete"):
            name = command[3].rpartition("\\")[2]
            found = self.tasks.pop(name, None) is not None
            return ok if found else subprocess.CompletedProcess(command, 1, "", "not found")
        if command[0] == "powershell":
            name = command[-1].split("-TaskName '")[1].split("'")[0]
            if name not in self.tasks:
                return subprocess.CompletedProcess(command, 1, "", "No MSFT_ScheduledTask objects found")
            record = json.loads((self.folder / f"{name}.json").read_text(encoding="utf-8"))
            if self.tasks[name] == "Running" and Path(record["stop_file"]).exists() and not self.ignores_stop:
                with open(record["log_file"], "a", encoding="utf-8") as log:
                    log.write("Stopped watching. Sliced 1, failed 0.\n")
                self.tasks[name] = "Ready"
                self.last_result[name] = 0
            return subprocess.CompletedProcess(command, 0, f"{self.tasks[name]} {self.last_result[name]}\n", "")
        return ok


@pytest.fixture
def windows_setup(tmp_path: Path) -> Path:
    """A BatchSlicer configuration, and a Python folder with pythonw.exe as in a Windows venv."""
    write_config(tmp_path / "bs", {"paths": {"data": tmp_path / "cache", "logs": tmp_path / "logs"}})
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("")
    (scripts / "pythonw.exe").write_text("")
    return tmp_path


def _manager(home: Path, fake: FakeTaskScheduler) -> WindowsTasks:
    return WindowsTasks(fake, folder=home / "services", environ={"USERNAME": "cesli", "USERDOMAIN": "SURFACE"},
                        sleep=lambda _: None)


def _install(home: Path, fake: FakeTaskScheduler, lines: list[str]) -> int:
    return run_service(
        ServiceOptions("install", run_arguments=("--config", str(home / "bs" / "config.yaml"), "--profile", "k2 pla")),
        manager=_manager(home, fake), write=lines.append, sleep=lambda _: None,
        python=str(home / "venv" / "Scripts" / "python.exe"),
    )


def test_the_task_runs_windowless_through_the_host(tmp_path: Path) -> None:
    """pythonw.exe runs the service host, which gets the log file, the stop file and the options."""
    (tmp_path / "pythonw.exe").write_text("")
    program, arguments = host_command(
        [str(tmp_path / "python.exe"), "-m", "batchslicer", "--profile", "k2 pla"],
        tmp_path / "service.log", tmp_path / "service.stop",
    )

    assert program == str(tmp_path / "pythonw.exe")
    assert arguments == ["-m", "batchslicer.cli.service_host", str(tmp_path / "service.log"),
                         str(tmp_path / "service.stop"), "--", "--profile", "k2 pla"]


def test_the_task_starts_at_sign_in_in_the_users_session(tmp_path: Path) -> None:
    """A logon trigger and an interactive token: it runs while the user is signed in, with a desktop."""
    xml = render_task("watch", "SURFACE\\cesli", "C:\\py\\pythonw.exe", ["-m", "x", "k2 pla & <b>"], tmp_path)

    assert "<LogonTrigger><Enabled>true</Enabled><UserId>SURFACE\\cesli</UserId></LogonTrigger>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml
    assert "<Arguments>-m x \"k2 pla &amp; &lt;b&gt;\"</Arguments>" in xml


def test_install_registers_starts_and_reports(windows_setup: Path) -> None:
    """install records the service, registers the task, starts it and shows its first output."""
    fake = FakeTaskScheduler(windows_setup / "services")
    lines: list[str] = []

    assert _install(windows_setup, fake, lines) == 0

    assert ("schtasks", "/Run", "/TN", "\\BatchSlicer\\watch") in fake.commands
    assert "<Command>" + str(windows_setup / "venv" / "Scripts" / "pythonw.exe") + "</Command>" in fake.xml["watch"]
    assert not list((windows_setup / "services").glob("*.xml"))  # the XML is only handed to schtasks
    assert "  | Watching C:/in for models; output to C:/out." in lines
    assert "It runs while you are signed in to Windows, without a window." in lines
    [service] = _manager(windows_setup, fake).installed()
    assert service.command[-4:] == ("--profile", "k2 pla", "--watch", "--no-prompt")


def test_a_failing_task_is_reported(windows_setup: Path) -> None:
    """A task that stops with an error shows its output, and install fails."""
    fake = FakeTaskScheduler(windows_setup / "services", first_line="BatchSlicer startup failed: no profile.",
                             exit_code=1)
    lines: list[str] = []

    assert _install(windows_setup, fake, lines) == 1
    assert "  | BatchSlicer startup failed: no profile." in lines
    assert any("did not start watching (it is failed)" in line for line in lines)


def test_uninstall_stops_like_ctrl_c_then_removes(windows_setup: Path) -> None:
    """uninstall asks the task to stop (no /End needed), then deletes it and its record."""
    fake = FakeTaskScheduler(windows_setup / "services")
    _install(windows_setup, fake, [])
    manager = _manager(windows_setup, fake)
    lines: list[str] = []

    assert run_service(ServiceOptions("status"), manager=manager, write=lines.append) == 0
    assert "watch: active" in lines

    assert run_service(ServiceOptions("uninstall"), manager=manager, write=lines.append) == 0
    assert not any(command[:2] == ("schtasks", "/End") for command in fake.commands)
    assert ("schtasks", "/Delete", "/TN", "\\BatchSlicer\\watch", "/F") in fake.commands
    assert "Stopped watching" in (windows_setup / "logs" / "service-watch.log").read_text(encoding="utf-8")
    assert manager.installed() == []
    assert not (windows_setup / "cache" / "service-watch.stop").exists()


def test_a_task_that_ignores_the_stop_request_is_ended(windows_setup: Path) -> None:
    """If the task is still running after the wait, it is ended."""
    fake = FakeTaskScheduler(windows_setup / "services", ignores_stop=True)
    _install(windows_setup, fake, [])

    assert run_service(ServiceOptions("uninstall"), manager=_manager(windows_setup, fake), write=lambda _: None) == 0
    assert ("schtasks", "/End", "/TN", "\\BatchSlicer\\watch") in fake.commands


def test_without_task_scheduler_the_terminal_is_suggested(windows_setup: Path) -> None:
    """Where schtasks does not work, nothing is written and a terminal window is suggested."""
    lines: list[str] = []
    fake = FakeTaskScheduler(windows_setup / "services", available=False)
    assert run_service(ServiceOptions("status"), manager=_manager(windows_setup, fake), write=lines.append) == 1
    assert "terminal window" in lines[0]


def test_windows_gets_task_scheduler(request: pytest.FixtureRequest) -> None:
    """Windows uses Task Scheduler."""
    request.getfixturevalue("windows")
    assert isinstance(system_manager(), WindowsTasks)


def test_the_host_turns_a_stop_file_into_ctrl_c(tmp_path: Path) -> None:
    """The host waits for the stop file, then interrupts BatchSlicer as Ctrl+C would."""
    stop_file = tmp_path / "service.stop"
    interrupted: list[bool] = []

    def sleep(_: float) -> None:
        stop_file.write_text("stop")  # the request arrives while the host waits

    service_host.watch_for_stop(stop_file, interrupt=lambda: interrupted.append(True), sleep=sleep)
    assert interrupted == [True]


def test_the_host_writes_batchslicer_output_to_the_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Output goes to the log file; a stale stop file is cleared first; mistakes give status 2."""
    import sys

    log_file, stop_file = tmp_path / "logs" / "service.log", tmp_path / "service.stop"
    stop_file.write_text("old request")
    monkeypatch.setattr("batchslicer.app.main", lambda options: print("ran", *options) or 0)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)

    assert service_host.main([str(log_file), str(stop_file), "--", "--profile", "k2"]) == 0
    assert log_file.read_text(encoding="utf-8") == "ran --profile k2\n"
    assert not stop_file.exists()
    assert service_host.main(["only-one-argument"]) == 2


@pytest.mark.parametrize(
    ("environ", "user"),
    [
        ({"USERNAME": "cesli", "USERDOMAIN": "SURFACEBOX"}, "SURFACEBOX\\cesli"),
        ({"USERNAME": "cesli", "USERDOMAIN": "WORKGROUP", "COMPUTERNAME": "SURFACEBOX"}, "SURFACEBOX\\cesli"),
        ({"USERNAME": "cesli"}, "cesli"),
    ],
)
def test_the_task_belongs_to_the_signed_in_account(tmp_path: Path, environ: dict[str, str], user: str) -> None:
    """Seen over SSH: USERDOMAIN is the workgroup, which Task Scheduler rejects; the computer name is used."""
    manager = WindowsTasks(FakeTaskScheduler(tmp_path), folder=tmp_path, environ=environ)
    assert manager._user() == user
