"""``batchslicer service``: keep the watch folder running in the background.

``install`` writes a systemd user service that runs BatchSlicer with the
given options plus ``--watch --no-prompt``, starts it and shows its first
lines of output; ``status`` lists the installed services and what they are
doing; ``uninstall`` stops and removes one. Paths in the options are made
absolute, and the configuration file in use now is named explicitly, so the
service does not depend on the folder it was installed from. The options
themselves are checked by :mod:`batchslicer.cli.arguments` before this runs.
"""

import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from batchslicer.core.config import find_config_file, get_config
from batchslicer.infrastructure.systemd import (
    DEFAULT_NAME,
    ServiceError,
    ServiceInfo,
    Systemd,
    check_name,
    installed_services,
    render_unit,
    unit_folder,
    unit_name,
)

SERVICE_ACTIONS = ("install", "status", "uninstall")
_PATH_OPTIONS = ("--input", "--output", "--config")
_ADDED_OPTIONS = ("--watch", "--no-prompt")
_STARTUP_WAIT_SECONDS = 15.0
_STARTED_MARK = "Watching "
"""The line BatchSlicer prints once it is watching."""


@dataclass(frozen=True, slots=True)
class ServiceOptions:
    """The choices for ``batchslicer service``."""

    action: str
    """``install``, ``status`` or ``uninstall``."""

    name: str | None = None
    """The service's name; ``None`` means the default (or every service, for status)."""

    run_arguments: tuple[str, ...] = ()
    """BatchSlicer's run options for ``install``, already checked."""


def run_service(
    options: ServiceOptions,
    *,
    systemd: Systemd | None = None,
    write: Callable[[str], None] = print,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    python: str | None = None,
) -> int:
    """Carry out ``options`` and return an exit status (0 when all went well)."""
    systemd = systemd or Systemd()
    try:
        systemd.check_available()
        if options.action == "install":
            return _install(options, systemd, write, environ, sleep, python or sys.executable)
        if options.action == "uninstall":
            return _uninstall(options, systemd, write, environ)
        return _status(options, systemd, write, environ)
    except (ServiceError, FileNotFoundError, OSError) as error:
        write(f"BatchSlicer service {options.action} failed: {error}")
        return 1


def service_command(run_arguments: Sequence[str], config: Path, python: str) -> list[str]:
    """Return the command a service runs: BatchSlicer with absolute paths, watching, no prompts."""
    arguments = [argument for argument in run_arguments if argument not in _ADDED_OPTIONS]
    arguments = absolute_paths(arguments)
    if not any(argument == "--config" or argument.startswith("--config=") for argument in arguments):
        arguments = ["--config", str(config.expanduser().absolute()), *arguments]
    return [python, "-m", "batchslicer", *arguments, *_ADDED_OPTIONS]


def absolute_paths(arguments: Sequence[str]) -> list[str]:
    """Return ``arguments`` with the folders and files of --input, --output and --config absolute."""
    result: list[str] = []
    expect_path = False
    for argument in arguments:
        if expect_path:
            result.append(str(Path(argument).expanduser().absolute()))
            expect_path = False
            continue
        option, equals, value = argument.partition("=")
        if option in _PATH_OPTIONS and equals:
            result.append(f"{option}={Path(value).expanduser().absolute()}")
        else:
            result.append(argument)
            expect_path = argument in _PATH_OPTIONS
    return result


def _install(
    options: ServiceOptions,
    systemd: Systemd,
    write: Callable[[str], None],
    environ: Mapping[str, str] | None,
    sleep: Callable[[float], None],
    python: str,
) -> int:
    name = check_name(options.name or DEFAULT_NAME)
    unit = unit_name(name)
    explicit = _option_value(options.run_arguments, "--config")
    config_path = find_config_file(Path(explicit) if explicit else None, environ=environ).absolute()
    config = get_config(config_path)
    working_directory = config.get_path("paths", "data")
    working_directory.mkdir(parents=True, exist_ok=True)
    command = service_command(options.run_arguments, config_path, python)

    path = unit_folder(environ) / unit
    replacing = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_unit(name, command, working_directory), encoding="utf-8")
    write(f"{'Replaced' if replacing else 'Wrote'} {path}")
    write(f"  runs: batchslicer {shlex.join(command[3:])}")
    systemd.reload()
    systemd.enable_and_restart(unit)

    state, log = _wait_until_watching(systemd, unit, sleep)
    for line in log:
        write(f"  | {line}")
    if state != "active" or not any(_STARTED_MARK in line for line in log):
        write(
            f"The service '{name}' did not start watching (it is {state}); see the lines above. "
            f"Fix the options and install it again, or remove it with "
            f"'batchslicer service uninstall --name {name}'."
        )
        return 1
    write("")
    write(f"The service '{name}' is watching, and starts again whenever you log in.")
    if systemd.lingering() is False:
        write(
            "It stops when you log out. To keep it running then (and start it at boot), "
            "run once: loginctl enable-linger"
        )
    write(f"Check it with 'batchslicer service status --name {name}'; follow it live with "
          f"'journalctl --user -u {unit} -f'.")
    return 0


def _wait_until_watching(
    systemd: Systemd, unit: str, sleep: Callable[[float], None]
) -> tuple[str, list[str]]:
    """Wait until the service watches or stops; return its state and recent output."""
    waited = 0.0
    while True:
        state = systemd.state(unit)
        log = systemd.recent_log(unit)
        started = any(_STARTED_MARK in line for line in log)
        if started or state in ("failed", "inactive") or waited >= _STARTUP_WAIT_SECONDS:
            return state, log
        sleep(0.5)
        waited += 0.5


def _uninstall(
    options: ServiceOptions,
    systemd: Systemd,
    write: Callable[[str], None],
    environ: Mapping[str, str] | None,
) -> int:
    name = check_name(options.name or DEFAULT_NAME)
    unit = unit_name(name)
    path = unit_folder(environ) / unit
    if not path.exists():
        names = ", ".join(service.name for service in installed_services(environ)) or "none"
        raise ServiceError(f"No service named '{name}' (installed: {names}).")
    try:
        systemd.disable_and_stop(unit)
    except ServiceError as error:
        write(f"Note: {error}")
    path.unlink()
    systemd.reload()
    write(f"Stopped and removed the service '{name}' ({path}).")
    return 0


def _status(
    options: ServiceOptions,
    systemd: Systemd,
    write: Callable[[str], None],
    environ: Mapping[str, str] | None,
) -> int:
    services = installed_services(environ)
    if options.name is not None:
        check_name(options.name)
        services = [service for service in services if service.name == options.name]
        if not services:
            raise ServiceError(f"No service named '{options.name}'.")
    if not services:
        write("No BatchSlicer services are installed. Add one with 'batchslicer service install'.")
        return 0
    healthy = True
    for service in services:
        state = systemd.state(service.unit)
        healthy = healthy and state == "active"
        write(f"{service.name}: {state}")
        write(f"  runs: batchslicer {_shown_command(service)}")
        if options.name is not None or len(services) == 1:
            for line in systemd.recent_log(service.unit):
                write(f"  | {line}")
        write(f"  log:  journalctl --user -u {service.unit} -f")
    if systemd.lingering() is False:
        write("Services stop when you log out; 'loginctl enable-linger' keeps them running.")
    return 0 if healthy else 1


def _shown_command(service: ServiceInfo) -> str:
    """Return a service's BatchSlicer options, without the Python and module in front."""
    command = list(service.command)
    if command[1:3] == ["-m", "batchslicer"]:
        command = command[3:]
    return shlex.join(command)


def _option_value(arguments: Sequence[str], option: str) -> str | None:
    """Return the value of ``option`` in ``arguments`` (``--opt VALUE`` or ``--opt=VALUE``)."""
    for index, argument in enumerate(arguments):
        if argument == option and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(option + "="):
            return argument.partition("=")[2]
    return None
