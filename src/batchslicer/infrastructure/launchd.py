"""Run BatchSlicer's watch folder as a launchd agent on macOS.

A service is a property list ``io.github.drak42.batchslicer.NAME.plist`` in
``~/Library/LaunchAgents`` whose program runs BatchSlicer with ``--watch
--no-prompt``. launchd starts it at every login (``RunAtLoad``), starts it
again if it stops with an error (``KeepAlive``), and writes its output to a
log file, since launchd keeps none itself. Stopping it sends SIGTERM, which
BatchSlicer treats like Ctrl+C: slicers are stopped and a drop being sliced
stays in the watched folder. ``launchctl`` loads, unloads and reports on the
agents in the signed-in user's session. This module writes, lists and removes
property lists and runs ``launchctl``; it does not decide what the service runs.
"""

import os
import plistlib
import shutil
import subprocess
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path

from batchslicer.infrastructure.service_manager import ServiceError, ServiceInfo, check_name

LABEL_PREFIX = "io.github.drak42.batchslicer."
_STOP_SECONDS = 60
"""How long launchd waits for a stop (slicers finishing their cleanup)."""
_RESTART_SECONDS = 30
"""How long launchd waits before starting a service that stopped with an error again."""

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def label(name: str) -> str:
    """Return the launchd label of service ``name``."""
    return f"{LABEL_PREFIX}{check_name(name)}"


def render_agent(name: str, command: Sequence[str], working_directory: Path, log_file: Path) -> bytes:
    """Return the property list that runs ``command`` as service ``name``."""
    return plistlib.dumps({
        "Label": label(name),
        "ProgramArguments": list(command),
        "WorkingDirectory": str(working_directory),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": _RESTART_SECONDS,
        "ExitTimeOut": _STOP_SECONDS,
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    })


class Launchd:
    """Manage BatchSlicer's launchd agents for the signed-in user.

    Implements :class:`~batchslicer.infrastructure.service_manager.ServiceManager`.
    """

    def __init__(
        self, runner: Runner | None = None, *, home: Path | None = None, uid: int | None = None
    ) -> None:
        """Use ``runner`` to run programs, and ``home`` and ``uid`` for the user (tests pass stand-ins)."""
        self._run = runner or _run
        self._home = home
        self._domain = f"gui/{os.getuid() if uid is None else uid}"  # type: ignore[attr-defined,unused-ignore]

    def check_available(self) -> None:
        """Raise :class:`ServiceError` unless agents can be loaded into the user's session."""
        if self._run(("launchctl", "print", self._domain)).returncode != 0:
            raise ServiceError(
                "launchd cannot start services for this user here: background services need "
                "you to be signed in at the Mac (not only over SSH). Sign in, or run "
                "'batchslicer --watch' in a Terminal window instead."
            )

    def definition_path(self, name: str) -> Path:
        """Return the property list of service ``name``."""
        return self._agents() / f"{label(name)}.plist"

    def write(self, name: str, command: Sequence[str], working_directory: Path, log_file: Path) -> None:
        """Write the property list, and start the log file afresh."""
        path = self.definition_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("", encoding="utf-8")
        path.write_bytes(render_agent(name, command, working_directory, log_file))

    def start(self, name: str) -> None:
        """Load the agent into the user's session (unloading an older copy first), which starts it."""
        target = f"{self._domain}/{label(name)}"
        self._run(("launchctl", "bootout", target))  # not loaded yet is fine
        self._run(("launchctl", "enable", target))
        self._checked("launchctl", "bootstrap", self._domain, str(self.definition_path(name)))

    def stop_and_remove(self, name: str) -> None:
        """Unload the agent (which stops it like Ctrl+C) and delete its property list."""
        self._run(("launchctl", "bootout", f"{self._domain}/{label(name)}"))
        self.definition_path(name).unlink(missing_ok=True)

    def installed(self) -> list[ServiceInfo]:
        """Return the BatchSlicer agents in ``~/Library/LaunchAgents``."""
        services: list[ServiceInfo] = []
        for path in sorted(self._agents().glob(f"{LABEL_PREFIX}*.plist")):
            name = path.name[len(LABEL_PREFIX) : -len(".plist")]
            info = _read(path)
            arguments = info.get("ProgramArguments", [])
            command = tuple(str(argument) for argument in arguments) if isinstance(arguments, list) else ()
            services.append(ServiceInfo(name=name, path=path, command=command))
        return services

    def state(self, name: str) -> str:
        """Return ``active`` while running, ``failed`` after an error, else ``inactive``."""
        result = self._run(("launchctl", "print", f"{self._domain}/{label(name)}"))
        if result.returncode != 0:
            return "inactive"
        values = _print_values(result.stdout)
        if values.get("state") == "running":
            return "active"
        if values.get("last exit code", "0") not in ("0", "(never exited)"):
            return "failed"
        return "inactive"

    def recent_log(self, name: str, lines: int = 15) -> list[str]:
        """Return the last lines of the service's log file."""
        log_file = self._log_file(name)
        if log_file is None:
            return []
        try:
            with log_file.open(encoding="utf-8", errors="replace") as stream:
                return [line.rstrip("\n") for line in deque(stream, maxlen=lines) if line.strip()]
        except OSError:
            return []

    def follow_hint(self, name: str) -> str:
        """Return the tail command that follows the service's log file."""
        log_file = self._log_file(name)
        return f'tail -f "{log_file}"' if log_file is not None else "batchslicer service status"

    def notes(self) -> list[str]:
        """Nothing extra: agents start at login and stop at logout."""
        return []

    def _agents(self) -> Path:
        return (self._home or Path.home()) / "Library" / "LaunchAgents"

    def _log_file(self, name: str) -> Path | None:
        value = _read(self.definition_path(name)).get("StandardOutPath")
        return Path(value) if isinstance(value, str) else None

    def _checked(self, *command: str) -> None:
        result = self._run(command)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise ServiceError(f"'{' '.join(command)}' failed: {message or f'exit {result.returncode}'}")


def _read(path: Path) -> dict[str, object]:
    """Return a property list's contents, or {} if it cannot be read."""
    try:
        with path.open("rb") as stream:
            loaded = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _print_values(text: str) -> dict[str, str]:
    """Return the top-level ``key = value`` lines of ``launchctl print`` output."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("\t") and not line.startswith("\t\t") and " = " in line:
            key, _, value = line.strip().partition(" = ")
            values.setdefault(key, value)
    return values


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a program and return its result; a missing program gives exit status 127."""
    if shutil.which(command[0]) is None:
        return subprocess.CompletedProcess(list(command), 127, "", f"{command[0]} not found")
    return subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90, check=False,
    )
