"""Describe what keeps BatchSlicer's watch folder running in the background.

Each system has its own service manager: systemd user services on Linux
(:mod:`batchslicer.infrastructure.systemd`) and launchd agents on macOS
(:mod:`batchslicer.infrastructure.launchd`). This module holds what they
share: the interface ``batchslicer service`` uses, the service names, and the
error raised when a service cannot be installed, checked or removed. It does
not install or run anything itself.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_NAME = "watch"
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")


class ServiceError(Exception):
    """Raised when a service cannot be installed, checked or removed."""


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """One installed BatchSlicer service."""

    name: str
    path: Path
    """The file that defines it (a systemd unit or a launchd property list)."""
    command: tuple[str, ...]
    """What the service runs."""


def check_name(name: str) -> str:
    """Return ``name`` if it can name a service, or raise :class:`ServiceError`."""
    if not _NAME_PATTERN.match(name):
        raise ServiceError(
            f"'{name}' cannot be a service name: use up to 40 letters, digits, dashes and "
            "underscores, starting with a letter or digit."
        )
    return name


class ServiceManager(Protocol):
    """What ``batchslicer service`` needs from a system's service manager."""

    def check_available(self) -> None:
        """Raise :class:`ServiceError`, saying what to do instead, if services cannot be used here."""
        ...

    def definition_path(self, name: str) -> Path:
        """Return the file that defines the service ``name``."""
        ...

    def write(self, name: str, command: Sequence[str], working_directory: Path, log_file: Path) -> None:
        """Write the definition of service ``name``, which runs ``command``.

        ``log_file`` receives the service's output where the system does not
        collect it itself.
        """
        ...

    def start(self, name: str) -> None:
        """Start ``name`` at every login from now on, and (re)start it now."""
        ...

    def stop_and_remove(self, name: str) -> None:
        """Stop ``name``, no longer start it at login, and delete its definition."""
        ...

    def installed(self) -> list[ServiceInfo]:
        """Return the installed BatchSlicer services, by name."""
        ...

    def state(self, name: str) -> str:
        """Return ``active`` while the service runs, else ``inactive``, ``failed``..."""
        ...

    def recent_log(self, name: str, lines: int = 15) -> list[str]:
        """Return the service's last lines of output."""
        ...

    def follow_hint(self, name: str) -> str:
        """Return a command that shows the service's output as it comes."""
        ...

    def notes(self) -> list[str]:
        """Return anything the user should know about services on this system (may be empty)."""
        ...
