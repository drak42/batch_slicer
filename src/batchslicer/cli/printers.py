"""Run ``batchslicer printers``: list the configured printers, for people or other programs.

Without options it prints one line per printer. ``--json`` prints them in a
small, stable format meant for other programs, such as 3dprintmon importing
your printers so they are set up once:

.. code-block:: json

    {"format": 1, "printers": [
        {"name": "k2plus", "type": "moonraker", "url": "http://192.168.1.50:7125",
         "api_key_env": "K2_KEY"}]}

An API key kept in an environment variable is given only by the variable's
name (``api_key_env``). One written in the configuration file is left out
unless ``--with-keys`` is given (``has_api_key`` says one exists). This module
only reads the configuration; it does not contact printers.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batchslicer.core.config import Config, find_config_file
from batchslicer.domain.printers import PrinterHost, PrinterHostError, printer_hosts

FORMAT_VERSION = 1
"""Raised only if the JSON changes in a way that would break a reader."""


@dataclass(frozen=True, slots=True)
class PrintersOptions:
    """Options for ``batchslicer printers``."""

    config: Path | None = None
    json: bool = False
    with_keys: bool = False


class PrintersError(ValueError):
    """Raised when the configured printers cannot be read."""


def run_printers(options: PrintersOptions) -> int:
    """List the configured printers and return an exit status (0, or 1 if they cannot be read)."""
    try:
        hosts = load_hosts(options.config)
    except PrintersError as error:
        if options.json:
            print(json.dumps({"format": FORMAT_VERSION, "error": str(error), "printers": []}))
        else:
            print(f"BatchSlicer: {error}")
        return 1
    if options.json:
        print(printers_json(hosts, with_keys=options.with_keys))
        return 0
    if not hosts:
        print("No printers are configured. Add them to the printers section (see the README).")
    for host in hosts:
        key = (
            f", API key from ${host.api_key_env}"
            if host.api_key_env
            else ", API key in the file"
            if host.api_key
            else ""
        )
        print(f"{host.describe()}{key}")
    return 0


def load_hosts(config: Path | None = None) -> list[PrinterHost]:
    """Return the configured printers, without needing their API-key variables to be set."""
    try:
        loaded = Config(find_config_file(config))
        loaded.load()
        return list(printer_hosts(loaded.section("printers"), require_keys=False).values())
    except (FileNotFoundError, KeyError, ValueError, PrinterHostError) as error:
        raise PrintersError(str(error)) from error


def printers_json(hosts: list[PrinterHost], *, with_keys: bool = False) -> str:
    """Return the printers in the ``--json`` format."""
    entries: list[dict[str, Any]] = []
    for host in hosts:
        entry: dict[str, Any] = {"name": host.name, "type": host.kind, "url": host.url}
        if host.api_key_env:
            entry["api_key_env"] = host.api_key_env
        elif host.api_key:
            entry["has_api_key"] = True
            if with_keys:
                entry["api_key"] = host.api_key
        entries.append(entry)
    return json.dumps({"format": FORMAT_VERSION, "printers": entries}, indent=2)
