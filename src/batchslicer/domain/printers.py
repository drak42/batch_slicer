"""Describe printers that G-code can be sent to.

A printer host is a networked printer named in the configuration's
``printers`` section, reached through Moonraker (the web API of Klipper
printers such as the Creality K1 and K2 series) or OctoPrint. This module only
describes them and checks the configured values, including reading an API key
from the environment variable a printer names; it does not contact printers.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

DEFAULT_PORT = 7125
"""Moonraker's usual port, used for an address given without one."""

MOONRAKER = "moonraker"
OCTOPRINT = "octoprint"
PRINTER_TYPES = (MOONRAKER, OCTOPRINT)
"""The kinds of printer connection, as written in the configuration's ``type``."""

_TYPE_NAMES = {MOONRAKER: "Moonraker", OCTOPRINT: "OctoPrint"}


class PrinterHostError(ValueError):
    """Raised when a configured printer cannot be used as written."""


@dataclass(frozen=True, slots=True)
class PrinterHost:
    """One printer that accepts G-code over the network."""

    name: str
    """The name used with --send, as written in the configuration."""

    url: str
    """The API's address, for example ``http://192.168.1.50:7125``, without a trailing ``/``."""

    api_key: str = ""
    """API key; empty when the printer does not ask for one (OctoPrint always does)."""

    kind: str = MOONRAKER
    """How the printer is reached: :data:`MOONRAKER` or :data:`OCTOPRINT`."""

    api_key_env: str = ""
    """The environment variable the API key was read from; empty when it is in the file."""

    def describe(self) -> str:
        """Return the name and address as shown to the user (and the API, if not Moonraker)."""
        if self.kind == MOONRAKER:
            return f"{self.name} ({self.url})"
        return f"{self.name} ({_TYPE_NAMES[self.kind]}, {self.url})"


def printer_hosts(
    section: Any,
    environ: Mapping[str, str] | None = None,
    *,
    require_keys: bool = True,
) -> dict[str, PrinterHost]:
    """Return the printers in a configuration ``printers`` section, by name.

    ``section`` maps names to ``{url, api_key, api_key_env, type}``; an empty or
    missing section gives no printers. ``api_key_env`` names an environment
    variable (in ``environ``, by default the process environment) that holds
    the API key, so the key need not be stored in the file. Raises
    :class:`PrinterHostError` for anything that cannot be used, naming the
    printer. With ``require_keys=False`` an ``api_key_env`` variable that is not
    set is accepted (the key is then empty), for listing printers without using them.
    """
    environ = os.environ if environ is None else environ
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
        unknown = set(map(str, values)) - {"url", "api_key", "api_key_env", "type"}
        if unknown:
            raise PrinterHostError(
                f"printers.{name} has unknown settings: {', '.join(sorted(unknown))}"
            )
        url = _checked_url(name, values.get("url"))
        api_key, api_key_env = _api_key(name, values, environ, require_keys)
        kind = values.get("type") or MOONRAKER
        if not isinstance(kind, str) or kind.casefold() not in PRINTER_TYPES:
            raise PrinterHostError(
                f"printers.{name}.type must be {' or '.join(PRINTER_TYPES)}, not {kind}."
            )
        kind = kind.casefold()
        if kind == OCTOPRINT and not api_key and not api_key_env:
            raise PrinterHostError(
                f"printers.{name}: OctoPrint needs an api_key or api_key_env (create a key "
                "in OctoPrint under Settings > Application Keys)."
            )
        hosts[name] = PrinterHost(
            name=name, url=url, api_key=api_key, kind=kind, api_key_env=api_key_env
        )
    return hosts


def _api_key(
    name: str, values: Mapping[Any, Any], environ: Mapping[str, str], require_keys: bool = True
) -> tuple[str, str]:
    """Return a printer's API key and the environment variable it came from ("" for the file)."""
    api_key = values.get("api_key") or ""
    if not isinstance(api_key, str):
        raise PrinterHostError(f"printers.{name}.api_key must be text.")
    variable = values.get("api_key_env") or ""
    if not variable:
        return api_key, ""
    if not isinstance(variable, str) or not _VARIABLE_PATTERN.match(variable):
        raise PrinterHostError(
            f"printers.{name}.api_key_env must be the name of an environment variable, "
            "such as MOONRAKER_API_KEY."
        )
    if api_key:
        raise PrinterHostError(
            f"printers.{name} sets both api_key and api_key_env; keep only one."
        )
    value = environ.get(variable, "").strip()
    if not value and require_keys:
        raise PrinterHostError(
            f"printers.{name}.api_key_env names {variable}, but that environment variable "
            "is not set (or is empty)."
        )
    return value, variable


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
