"""Run BatchSlicer's watch folder as a Windows scheduled task.

A service is a Task Scheduler task ``\\BatchSlicer\\NAME`` that starts when the
user signs in and runs in their session, so slicers that need a desktop
(Bambu Studio on Windows) work. It runs BatchSlicer through
:mod:`batchslicer.cli.service_host` with ``pythonw.exe``, so no console window
opens; the output goes to a log file. To stop it like Ctrl+C, a stop-request
file is written and the task is given time to finish; only if it does not is
the task ended. The task is registered from an XML definition with
``schtasks``; its state is read with PowerShell's ``Get-ScheduledTask``, whose
values are the same in every Windows language. What was installed is kept in
``NAME.json`` in BatchSlicer's ``services`` folder. This module writes, lists
and removes tasks; it does not decide what the service runs.
"""

import json
import os
import shutil
import subprocess
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from xml.sax.saxutils import escape

from batchslicer.core.locations import user_config_file
from batchslicer.infrastructure.service_manager import ServiceError, ServiceInfo, check_name

TASK_FOLDER = "\\BatchSlicer\\"
HOST_MODULE = "batchslicer.cli.service_host"
STOP_SECONDS = 60.0
"""How long a stop request is given before the task is ended."""
_RUNNING_RESULT = 267009
"""Task Scheduler's result while a task is still running."""
_NEVER_RUN_RESULT = 267011
"""Task Scheduler's result for a task that has not run yet."""

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def task_name(name: str) -> str:
    """Return the full Task Scheduler name of service ``name``."""
    return f"{TASK_FOLDER}{check_name(name)}"


def host_command(command: Sequence[str], log_file: Path, stop_file: Path) -> tuple[str, list[str]]:
    """Return the program and arguments that run ``command`` through the service host.

    ``command`` is ``[python, "-m", "batchslicer", options...]``; it runs with
    ``pythonw.exe`` from the same folder when there is one, so no window opens.
    """
    if list(command[1:3]) != ["-m", "batchslicer"]:
        raise ServiceError(f"Cannot run this as a Windows service: {' '.join(command)}")
    python = Path(command[0])
    windowless = python.with_name("pythonw.exe")
    program = str(windowless) if windowless.is_file() else str(python)
    return program, ["-m", HOST_MODULE, str(log_file), str(stop_file), "--", *command[3:]]


def render_task(name: str, user: str, program: str, arguments: Sequence[str], working_directory: Path) -> str:
    """Return the Task Scheduler XML for a task that runs at ``user``'s sign-in, in their session."""
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-16"?>',
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
        "  <RegistrationInfo>",
        f"    <Description>BatchSlicer watch folder ({escape(name)}). Created by 'batchslicer service "
        f"install'; remove it with 'batchslicer service uninstall --name {escape(name)}'.</Description>",
        "  </RegistrationInfo>",
        "  <Triggers>",
        f"    <LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger>",
        "  </Triggers>",
        "  <Principals>",
        '    <Principal id="Author">',
        f"      <UserId>{escape(user)}</UserId>",
        "      <LogonType>InteractiveToken</LogonType>",
        "      <RunLevel>LeastPrivilege</RunLevel>",
        "    </Principal>",
        "  </Principals>",
        "  <Settings>",
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
        "    <Enabled>true</Enabled>",
        "  </Settings>",
        '  <Actions Context="Author">',
        "    <Exec>",
        f"      <Command>{escape(program)}</Command>",
        f"      <Arguments>{escape(subprocess.list2cmdline(list(arguments)))}</Arguments>",
        f"      <WorkingDirectory>{escape(str(working_directory))}</WorkingDirectory>",
        "    </Exec>",
        "  </Actions>",
        "</Task>",
        "",
    ])


class WindowsTasks:
    """Manage BatchSlicer's scheduled tasks for the signed-in Windows user.

    Implements :class:`~batchslicer.infrastructure.service_manager.ServiceManager`.
    """

    def __init__(
        self,
        runner: Runner | None = None,
        *,
        folder: Path | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Use ``runner`` to run programs and ``folder`` for the service records (tests pass stand-ins)."""
        self._run = runner or _run
        self._environ = os.environ if environ is None else environ
        self._folder = folder
        self._sleep = sleep

    def check_available(self) -> None:
        """Raise :class:`ServiceError` unless Task Scheduler can be used."""
        if self._run(("schtasks", "/Query", "/FO", "CSV", "/NH")).returncode != 0:
            raise ServiceError(
                "Task Scheduler cannot be used here (schtasks does not work). Run "
                "'batchslicer --watch' in a terminal window instead."
            )

    def definition_path(self, name: str) -> Path:
        """Return the record of service ``name``."""
        return self._services() / f"{check_name(name)}.json"

    def write(self, name: str, command: Sequence[str], working_directory: Path, log_file: Path) -> None:
        """Record the service and start its log file afresh; :meth:`start` registers the task."""
        stop_file = working_directory / f"service-{name}.stop"
        program, arguments = host_command(command, log_file, stop_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        self._stop(name)  # a running older version writes to the same log
        log_file.write_text("", encoding="utf-8")
        path = self.definition_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "command": list(command),
            "program": program,
            "arguments": arguments,
            "working_directory": str(working_directory),
            "log_file": str(log_file),
            "stop_file": str(stop_file),
        }, indent=2), encoding="utf-8")

    def start(self, name: str) -> None:
        """Register the task (replacing an older one) and start it now."""
        record = self._record(name)
        arguments = record.get("arguments")
        xml_file = self._services() / f"{name}.xml"
        xml_file.write_text(
            render_task(
                name, self._user(), str(record.get("program", "")),
                [str(argument) for argument in arguments] if isinstance(arguments, list) else [],
                Path(str(record.get("working_directory", "."))),
            ),
            encoding="utf-16",
        )
        try:
            self._checked("schtasks", "/Create", "/TN", task_name(name), "/XML", str(xml_file), "/F")
        finally:
            xml_file.unlink(missing_ok=True)
        self._checked("schtasks", "/Run", "/TN", task_name(name))

    def stop_and_remove(self, name: str) -> None:
        """Stop the task like Ctrl+C, remove it from Task Scheduler and delete its record."""
        try:
            self._stop(name)
            self._run(("schtasks", "/Delete", "/TN", task_name(name), "/F"))
        finally:
            self.definition_path(name).unlink(missing_ok=True)

    def installed(self) -> list[ServiceInfo]:
        """Return the recorded BatchSlicer services."""
        services: list[ServiceInfo] = []
        for path in sorted(self._services().glob("*.json")):
            command = _load(path).get("command", [])
            services.append(ServiceInfo(
                name=path.stem, path=path,
                command=tuple(str(part) for part in command) if isinstance(command, list) else (),
            ))
        return services

    def state(self, name: str) -> str:
        """Return ``active`` while running, ``failed`` after an error, else ``inactive``."""
        script = (
            f"$t = Get-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{check_name(name)}' "
            "-ErrorAction Stop; $i = $t | Get-ScheduledTaskInfo; \"$($t.State) $($i.LastTaskResult)\""
        )
        result = self._run(("powershell", "-NoProfile", "-NonInteractive", "-Command", script))
        state, _, last = result.stdout.strip().partition(" ")
        if result.returncode != 0 or not state:
            return "inactive"
        if state == "Running":
            return "active"
        if last.strip() not in ("", "0", str(_RUNNING_RESULT), str(_NEVER_RUN_RESULT)):
            return "failed"
        return "inactive"

    def recent_log(self, name: str, lines: int = 15) -> list[str]:
        """Return the last lines of the service's log file."""
        value = self._record(name).get("log_file")
        if not isinstance(value, str):
            return []
        try:
            with open(value, encoding="utf-8", errors="replace") as stream:
                return [line.rstrip("\n") for line in deque(stream, maxlen=lines) if line.strip()]
        except OSError:
            return []

    def follow_hint(self, name: str) -> str:
        """Return the PowerShell command that follows the service's log file."""
        value = self._record(name).get("log_file")
        return f'Get-Content "{value}" -Wait -Tail 20' if value else "batchslicer service status"

    def notes(self) -> list[str]:
        """Say when the service runs."""
        return ["It runs while you are signed in to Windows, without a window."]

    def _stop(self, name: str) -> None:
        """Ask a running task to stop like Ctrl+C; end it if it has not stopped in time."""
        if self.state(name) != "active":
            return
        stop_value = self._record(name).get("stop_file")
        if isinstance(stop_value, str):
            stop_file = Path(stop_value)
            stop_file.parent.mkdir(parents=True, exist_ok=True)
            stop_file.write_text("stop\n", encoding="utf-8")
            waited = 0.0
            while waited < STOP_SECONDS and self.state(name) == "active":
                self._sleep(1.0)
                waited += 1.0
            stop_file.unlink(missing_ok=True)
        if self.state(name) == "active":
            self._run(("schtasks", "/End", "/TN", task_name(name)))

    def _services(self) -> Path:
        return self._folder or user_config_file(self._environ).parent / "services"

    def _record(self, name: str) -> dict[str, object]:
        return _load(self.definition_path(name))

    def _user(self) -> str:
        user = self._environ.get("USERNAME", "")
        domain = self._environ.get("USERDOMAIN", "")
        if not user:
            raise ServiceError("Cannot tell which Windows user this is (USERNAME is not set).")
        if not domain or domain.upper() == "WORKGROUP":
            # Outside a desktop session (SSH) USERDOMAIN can be the workgroup, which is
            # not an account domain; a local or Microsoft account belongs to the computer.
            domain = self._environ.get("COMPUTERNAME", "")
        return f"{domain}\\{user}" if domain else user

    def _checked(self, *command: str) -> None:
        result = self._run(command)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise ServiceError(f"'{' '.join(command)}' failed: {message or f'exit {result.returncode}'}")


def _load(path: Path) -> dict[str, object]:
    """Return a service record, or {} if it cannot be read."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a program and return its result; a missing program gives exit status 127."""
    if shutil.which(command[0]) is None:
        return subprocess.CompletedProcess(list(command), 127, "", f"{command[0]} not found")
    return subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90, check=False,
    )
