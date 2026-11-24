"""Run BatchSlicer's watch folder as a systemd user service.

A service is a unit file ``batchslicer-NAME.service`` in the user's systemd
folder (``~/.config/systemd/user``) whose ``ExecStart`` runs BatchSlicer with
``--watch --no-prompt``. It is stopped with SIGINT, so stopping it behaves
like pressing Ctrl+C: slicers are stopped and a drop being sliced stays in the
watched folder. ``systemctl --user`` and ``journalctl --user`` do the rest.
This module writes, lists and removes unit files and runs those programs; it
does not decide what the service runs. Output goes to the journal, so the log
file a service manager may be given is not used here.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from batchslicer.infrastructure.service_manager import ServiceError, ServiceInfo, check_name

UNIT_PREFIX = "batchslicer-"
_STOP_SECONDS = 60
"""How long systemd waits for a stop (slicers finishing their cleanup)."""

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def unit_name(name: str) -> str:
    """Return the systemd unit for a service name: ``batchslicer-NAME.service``."""
    return f"{UNIT_PREFIX}{check_name(name)}.service"


def unit_folder(environ: Mapping[str, str] | None = None) -> Path:
    """Return the folder for the user's own systemd units."""
    environ = os.environ if environ is None else environ
    value = environ.get("XDG_CONFIG_HOME", "")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".config"
    return base / "systemd" / "user"


def render_unit(name: str, command: Sequence[str], working_directory: Path) -> str:
    """Return the text of the unit file that runs ``command``."""
    return "\n".join([
        "# Created by 'batchslicer service install'. Remove it with",
        f"# 'batchslicer service uninstall --name {name}'.",
        "[Unit]",
        f"Description=BatchSlicer watch folder ({name})",
        "Documentation=https://github.com/drak42/batch_slicer#watch-folder",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={' '.join(quote(argument) for argument in command)}",
        f"WorkingDirectory={quote(str(working_directory))}",
        "Environment=PYTHONUNBUFFERED=1",
        "# Stop like Ctrl+C, so slicers are stopped cleanly.",
        "KillSignal=SIGINT",
        f"TimeoutStopSec={_STOP_SECONDS}",
        "Restart=on-failure",
        "RestartSec=30",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def quote(argument: str) -> str:
    """Quote one argument for a systemd ``ExecStart`` line.

    Specifiers (``%``) and variables (``$``) are escaped, so the value is
    passed exactly as given.
    """
    text = argument.replace("%", "%%").replace("$", "$$")
    if text and not re.search(r'[\s"\'\\;]', text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def unquote_command(line: str) -> tuple[str, ...]:
    """Return the arguments of an ``ExecStart`` value written by :func:`render_unit`."""
    arguments: list[str] = []
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"|(\S+)', line):
        quoted, plain = match.groups()
        text = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else plain
        arguments.append(text.replace("$$", "$").replace("%%", "%"))
    return tuple(arguments)


def installed_services(environ: Mapping[str, str] | None = None) -> list[ServiceInfo]:
    """Return the BatchSlicer services in the user's systemd folder, by name."""
    folder = unit_folder(environ)
    services: list[ServiceInfo] = []
    for path in sorted(folder.glob(f"{UNIT_PREFIX}*.service")):
        name = path.name[len(UNIT_PREFIX) : -len(".service")]
        command: tuple[str, ...] = ()
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ExecStart="):
                    command = unquote_command(line[len("ExecStart=") :])
        except OSError:
            pass
        services.append(ServiceInfo(name=name, path=path, command=command))
    return services


class Systemd:
    """Run ``systemctl --user``, ``journalctl --user`` and ``loginctl`` for the current user.

    Implements :class:`~batchslicer.infrastructure.service_manager.ServiceManager`.
    """

    def __init__(self, runner: Runner | None = None, environ: Mapping[str, str] | None = None) -> None:
        """Use ``runner`` to run programs and ``environ`` to find the unit folder (tests pass stand-ins)."""
        self._run = runner or _run
        self._environ = environ

    def definition_path(self, name: str) -> Path:
        """Return the unit file of service ``name``."""
        return unit_folder(self._environ) / unit_name(name)

    def write(self, name: str, command: Sequence[str], working_directory: Path, log_file: Path) -> None:
        """Write the unit file; the output goes to the journal, not ``log_file``."""
        path = self.definition_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_unit(name, command, working_directory), encoding="utf-8")

    def start(self, name: str) -> None:
        """Read the unit, start it at login from now on, and (re)start it now."""
        self.reload()
        self.enable_and_restart(unit_name(name))

    def stop_and_remove(self, name: str) -> None:
        """Stop and disable the unit (a failure to stop is not fatal) and delete it."""
        try:
            self.disable_and_stop(unit_name(name))
        finally:
            self.definition_path(name).unlink(missing_ok=True)
            self.reload()

    def installed(self) -> list[ServiceInfo]:
        """Return the BatchSlicer units in the user's systemd folder."""
        return installed_services(self._environ)

    def follow_hint(self, name: str) -> str:
        """Return the journalctl command that follows the service's output."""
        return f"journalctl --user -u {unit_name(name)} -f"

    def notes(self) -> list[str]:
        """Say so when services stop at logout (no lingering)."""
        if self.lingering() is False:
            return [
                "Services stop when you log out. To keep them running then (and start them "
                "at boot), run once: loginctl enable-linger"
            ]
        return []

    def check_available(self) -> None:
        """Raise :class:`ServiceError` unless the user's systemd can be used."""
        if self._run(("systemctl", "--user", "--version")).returncode != 0:
            raise ServiceError(
                "systemd's user services are not available here (they need Linux with "
                "systemd; systemctl --user does not work). Run 'batchslicer --watch' in a "
                "terminal window instead (on Linux, tmux or screen keep it running)."
            )

    def reload(self) -> None:
        """Make systemd read changed unit files."""
        self._checked("systemctl", "--user", "daemon-reload")

    def enable_and_restart(self, unit: str) -> None:
        """Start ``unit`` at login from now on, and (re)start it now."""
        self._checked("systemctl", "--user", "enable", unit)
        self._checked("systemctl", "--user", "restart", unit)

    def disable_and_stop(self, unit: str) -> None:
        """Stop ``unit`` and no longer start it at login."""
        self._checked("systemctl", "--user", "disable", "--now", unit)

    def state(self, name: str) -> str:
        """Return ``active``, ``inactive``, ``failed``, ``activating``..."""
        result = self._run(("systemctl", "--user", "is-active", unit_name(name)))
        return result.stdout.strip() or "unknown"

    def recent_log(self, name: str, lines: int = 15) -> list[str]:
        """Return the service's last lines of output from the journal."""
        result = self._run(
            ("journalctl", "--user", "--unit", unit_name(name), "--lines", str(lines), "--no-pager",
             "--output", "cat")
        )
        return [line for line in result.stdout.splitlines() if line.strip()]

    def lingering(self) -> bool | None:
        """Return whether the user's services keep running after logout, or None if unknown."""
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if not user:
            return None
        result = self._run(("loginctl", "show-user", user, "--property", "Linger"))
        value = result.stdout.strip()
        if result.returncode != 0 or not value.startswith("Linger="):
            return None
        return value == "Linger=yes"

    def _checked(self, *command: str) -> None:
        result = self._run(command)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise ServiceError(f"'{' '.join(command)}' failed: {message or f'exit {result.returncode}'}")


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a program and return its result; a missing program gives exit status 127."""
    if shutil.which(command[0]) is None:
        return subprocess.CompletedProcess(list(command), 127, "", f"{command[0]} not found")
    return subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
    )
