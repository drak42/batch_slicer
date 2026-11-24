"""``batchslicer service``: keep the watch folder running in the background.

``install`` writes a background service (a systemd user service on Linux, a
launchd agent on macOS, a scheduled task on Windows) that runs BatchSlicer with the given options plus
``--watch --no-prompt`` (with ``--web``: ``batchslicer web`` with the options
plus ``--no-prompt``, the web page and its watch), starts it and shows its
first lines of output; ``status`` lists the installed services and what they are
doing; ``uninstall`` stops and removes one. Paths in the options are made
absolute, and the configuration file in use now is named explicitly, so the
service does not depend on the folder it was installed from. The options
themselves are checked by :mod:`batchslicer.cli.arguments` before this runs.
:func:`watch_targets` tells the web page which folders installed services watch.
"""

import contextlib
import io
import shlex
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from batchslicer.cli.web import DEFAULT_PORT, INSTALL_HINT, WebOptions, missing_modules
from batchslicer.core import locations
from batchslicer.core.config import find_config_file, get_config
from batchslicer.infrastructure.launchd import Launchd
from batchslicer.infrastructure.service_manager import (
    DEFAULT_NAME,
    ServiceError,
    ServiceInfo,
    ServiceManager,
    check_name,
)
from batchslicer.infrastructure.systemd import Systemd
from batchslicer.infrastructure.windows_tasks import WindowsTasks

SERVICE_ACTIONS = ("install", "status", "uninstall")
WEB_DEFAULT_NAME = "web"
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

    web: bool = False
    """Whether ``install`` runs the web page with its watch (``batchslicer web``)."""


@dataclass(frozen=True, slots=True)
class WatchTarget:
    """A folder an installed service watches."""

    name: str
    folder: Path


def run_service(
    options: ServiceOptions,
    *,
    manager: ServiceManager | None = None,
    write: Callable[[str], None] = print,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    python: str | None = None,
) -> int:
    """Carry out ``options`` and return an exit status (0 when all went well)."""
    manager = manager or system_manager()
    try:
        manager.check_available()
        if options.action == "install":
            return _install(options, manager, write, environ, sleep, python or sys.executable)
        if options.action == "uninstall":
            return _uninstall(options, manager, write)
        return _status(options, manager, write)
    except (ServiceError, FileNotFoundError, OSError) as error:
        write(f"BatchSlicer service {options.action} failed: {error}")
        return 1


def system_manager() -> ServiceManager:
    """Return this system's service manager: Task Scheduler, launchd or systemd."""
    if locations.is_windows():
        return WindowsTasks()
    if locations.is_macos():
        return Launchd()
    return Systemd()


def service_command(
    run_arguments: Sequence[str], config: Path, python: str, *, web: bool = False
) -> list[str]:
    """Return the command a service runs: BatchSlicer with absolute paths, watching, no prompts.

    With ``web``, it runs ``batchslicer web``, which adds ``--watch`` itself.
    """
    arguments = [argument for argument in run_arguments if argument not in _ADDED_OPTIONS]
    arguments = absolute_paths(arguments)
    if not any(argument == "--config" or argument.startswith("--config=") for argument in arguments):
        arguments = ["--config", str(config.expanduser().absolute()), *arguments]
    if web:
        return [python, "-m", "batchslicer", "web", *arguments, "--no-prompt"]
    return [python, "-m", "batchslicer", *arguments, *_ADDED_OPTIONS]


def watch_targets(manager: ServiceManager | None = None) -> list[WatchTarget]:
    """Return the folders the installed services watch, by service name.

    A service whose command cannot be read, or whose configuration cannot be
    loaded, is left out; nothing is raised.
    """
    from batchslicer.cli.arguments import RunOptions, parse_arguments

    try:
        services = (manager or system_manager()).installed()
    except (ServiceError, OSError):
        return []
    targets = []
    for service in services:
        arguments = _batchslicer_arguments(service)
        try:
            with contextlib.redirect_stderr(io.StringIO()):  # a mistake is skipped, not shown
                if arguments[:1] == ["web"]:
                    page = parse_arguments(arguments)
                    arguments = list(page.run_arguments) if isinstance(page, WebOptions) else []
                options = parse_arguments([*arguments, "--watch", "--no-prompt"])
            if not isinstance(options, RunOptions):
                continue
            folder = options.input or get_config(find_config_file(options.config)).get_path("paths", "incoming")
        except (SystemExit, FileNotFoundError, KeyError, ValueError, OSError):
            continue
        targets.append(WatchTarget(service.name, folder.expanduser().absolute()))
    return targets


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
    manager: ServiceManager,
    write: Callable[[str], None],
    environ: Mapping[str, str] | None,
    sleep: Callable[[float], None],
    python: str,
) -> int:
    name = check_name(options.name or (WEB_DEFAULT_NAME if options.web else DEFAULT_NAME))
    if options.web and missing_modules():
        raise ServiceError(f"Missing: {', '.join(missing_modules())}. {INSTALL_HINT}")
    explicit = _option_value(options.run_arguments, "--config")
    config_path = find_config_file(Path(explicit) if explicit else None, environ=environ).absolute()
    config = get_config(config_path)
    working_directory = config.get_path("paths", "data")
    working_directory.mkdir(parents=True, exist_ok=True)
    log_file = config.get_path("paths", "logs") / f"service-{name}.log"
    command = service_command(options.run_arguments, config_path, python, web=options.web)

    path = manager.definition_path(name)
    replacing = path.exists()
    manager.write(name, command, working_directory, log_file)
    write(f"{'Replaced' if replacing else 'Wrote'} {path}")
    write(f"  runs: batchslicer {shlex.join(command[3:])}")
    manager.start(name)

    state, log = _wait_until_watching(manager, name, sleep)
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
    if options.web:
        port = _option_value(options.run_arguments, "--port") or str(DEFAULT_PORT)
        write(f"Its web page: http://127.0.0.1:{port} (on this computer only)")
    for note in manager.notes():
        write(note)
    write(f"Check it with 'batchslicer service status --name {name}'; follow it live with "
          f"'{manager.follow_hint(name)}'.")
    return 0


def _wait_until_watching(
    manager: ServiceManager, name: str, sleep: Callable[[float], None]
) -> tuple[str, list[str]]:
    """Wait until the service watches or stops; return its state and recent output."""
    waited = 0.0
    while True:
        state = manager.state(name)
        log = manager.recent_log(name)
        started = any(_STARTED_MARK in line for line in log)
        if started or state in ("failed", "inactive") or waited >= _STARTUP_WAIT_SECONDS:
            return state, log
        sleep(0.5)
        waited += 0.5


def _uninstall(options: ServiceOptions, manager: ServiceManager, write: Callable[[str], None]) -> int:
    name = check_name(options.name or DEFAULT_NAME)
    path = manager.definition_path(name)
    if not path.exists():
        names = ", ".join(service.name for service in manager.installed()) or "none"
        raise ServiceError(f"No service named '{name}' (installed: {names}).")
    try:
        manager.stop_and_remove(name)
    except ServiceError as error:
        write(f"Note: {error}")
    write(f"Stopped and removed the service '{name}' ({path}).")
    return 0


def _status(options: ServiceOptions, manager: ServiceManager, write: Callable[[str], None]) -> int:
    services = manager.installed()
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
        state = manager.state(service.name)
        healthy = healthy and state == "active"
        write(f"{service.name}: {state}")
        write(f"  runs: batchslicer {_shown_command(service)}")
        if options.name is not None or len(services) == 1:
            for line in manager.recent_log(service.name):
                write(f"  | {line}")
        write(f"  log:  {manager.follow_hint(service.name)}")
    for note in manager.notes():
        write(note)
    return 0 if healthy else 1


def _shown_command(service: ServiceInfo) -> str:
    """Return a service's BatchSlicer options, without the Python and module in front."""
    return shlex.join(_batchslicer_arguments(service))


def _batchslicer_arguments(service: ServiceInfo) -> list[str]:
    """Return what a service passes to BatchSlicer, without the Python and module in front."""
    command = list(service.command)
    return command[3:] if command[1:3] == ["-m", "batchslicer"] else command


def _option_value(arguments: Sequence[str], option: str) -> str | None:
    """Return the value of ``option`` in ``arguments`` (``--opt VALUE`` or ``--opt=VALUE``)."""
    for index, argument in enumerate(arguments):
        if argument == option and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(option + "="):
            return argument.partition("=")[2]
    return None
