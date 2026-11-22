"""Describe printers that G-code can be sent to.

A printer host is a networked printer named in the configuration's
``printers`` section, reached through Moonraker (the web API of Klipper
printers such as the Creality K1 and K2 series). This module only describes
them and checks the configured values; it does not contact printers.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

DEFAULT_PORT = 7125
"""Moonraker's usual port, used for an address given without one."""


class PrinterHostError(ValueError):
    """Raised when a configured printer cannot be used as written."""


@dataclass(frozen=True, slots=True)
class PrinterHost:
    """One printer that accepts G-code over the network."""

    name: str
    """The name used with --send, as written in the configuration."""

    url: str
    """Moonraker's address, for example ``http://192.168.1.50:7125``, without a trailing ``/``."""

    api_key: str = ""
    """Moonraker API key; empty when the printer does not ask for one."""

    def describe(self) -> str:
        """Return the name and address as shown to the user."""
        return f"{self.name} ({self.url})"


def printer_hosts(section: Any) -> dict[str, PrinterHost]:
    """Return the printers in a configuration ``printers`` section, by name.

    ``section`` maps names to ``{url, api_key}``; an empty or missing section
    gives no printers. Raises :class:`PrinterHostError` for anything that
    cannot be used, naming the printer.
    """
    if section in (None, ""):
        return {}
    if not isinstance(section, Mapping):
        raise PrinterHostError("printers must map printer names to their settings.")
    hosts: dict[str, PrinterHost] = {}
    for name, values in section.items():
        name = str(name)
        if not _NAME_PATTERN.match(name):
            raise PrinterHostError(
                f"printers.{name}: use letters, digits, dots, dashes and underscores "
                "for printer names."
            )
        if not isinstance(values, Mapping):
            raise PrinterHostError(f"printers.{name} must have a url setting.")
        unknown = set(map(str, values)) - {"url", "api_key"}
        if unknown:
            raise PrinterHostError(
                f"printers.{name} has unknown settings: {', '.join(sorted(unknown))}"
            )
        url = _checked_url(name, values.get("url"))
        api_key = values.get("api_key") or ""
        if not isinstance(api_key, str):
            raise PrinterHostError(f"printers.{name}.api_key must be text.")
        hosts[name] = PrinterHost(name=name, url=url, api_key=api_key)
    return hosts


def host_from_address(text: str) -> PrinterHost | None:
    """Return a printer for an address given directly (``--send 192.168.1.50``).

    An address is anything with ``://``, ``:`` or ``.`` in it: an IP address,
    a host name such as ``k2.local``, either with a port, or a full URL.
    Without a port or scheme, Moonraker's usual port 7125 is used. Returns
    ``None`` for a plain name (to be looked up in the configuration).
    """
    text = text.strip()
    if not any(mark in text for mark in ("://", ":", ".")):
        return None
    problem = (
        f"'{text}' is not a printer address (expected something like 192.168.1.50, "
        "k2.local:4408 or http://192.168.1.50:7125)"
    )
    try:
        url = _checked_url(text, text)
        parts = urlsplit(url)
        port = parts.port
    except (PrinterHostError, ValueError) as error:
        raise PrinterHostError(problem) from error
    if "://" not in text and port is None:
        url = parts._replace(netloc=f"{parts.netloc}:{DEFAULT_PORT}").geturl()
    return PrinterHost(name=text.rstrip("/"), url=url)


def _checked_url(name: str, value: Any) -> str:
    """Return a printer's address without a trailing ``/``, or explain what is wrong."""
    if not isinstance(value, str) or not value.strip():
        raise PrinterHostError(
            f"printers.{name}.url is missing; set it to the printer's address, "
            "for example http://192.168.1.50:7125"
        )
    url = value.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PrinterHostError(
            f"printers.{name}.url is not a web address: {value} "
            "(expected something like http://192.168.1.50:7125)"
        )
    return url
