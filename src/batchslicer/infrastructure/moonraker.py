"""Talk to a printer through Moonraker, the web API of Klipper printers.

Two calls are used: ``GET /server/info`` to check that the printer answers,
and ``POST /server/files/upload`` to store a G-code file in the printer's
``gcodes`` folder, optionally starting it as a print. On Creality printers
with a CFS, ``GET /printer/objects/query?box&filament_rack`` tells which
filaments are loaded. Files are streamed from
disk, so large G-code is not read into memory. Only the Python standard
library is used. This module does not choose files or decide whether to
start a print; that is the sending service's job.
"""

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from batchslicer.domain.filaments import LoadedFilament
from batchslicer.domain.printers import PrinterHost
from batchslicer.infrastructure.printer_api import (
    PrinterError,
    PrinterStatus,
    UploadResult,
    multipart_body,
    send_json,
    upload_request,
)

MoonrakerError = PrinterError
"""Kept as a name for errors from Moonraker; the same as :class:`PrinterError`."""

__all__ = ["MoonrakerClient", "MoonrakerError", "UploadResult"]


class MoonrakerClient:
    """Send requests to one printer's Moonraker."""

    def __init__(
        self,
        host: PrinterHost,
        *,
        timeout_seconds: float = 10.0,
        upload_timeout_seconds: float = 300.0,
    ) -> None:
        """Store the printer and how long to wait for it."""
        self._host = host
        self._timeout = timeout_seconds
        self._upload_timeout = upload_timeout_seconds

    @property
    def host(self) -> PrinterHost:
        """Return the printer this client talks to."""
        return self._host

    def server_info(self) -> dict[str, Any]:
        """Return Moonraker's ``/server/info`` (includes ``klippy_state``)."""
        return self._request(Request(self._url("/server/info"), headers=self._headers()), self._timeout)

    def status(self) -> PrinterStatus:
        """Return Klipper's state; it is ready when Klipper says ``ready``."""
        info = self.server_info()
        state = str(info.get("klippy_state", "unknown"))
        version = str(info.get("moonraker_version", "") or "").strip("?")  # Creality's says "?"
        return PrinterStatus(
            state=f"Klipper is {state}",
            ready=state == "ready",
            software=f"Moonraker {version}".strip(),
        )

    def loaded_filaments(self) -> list[LoadedFilament]:
        """Return the filaments loaded in the printer's CFS and external spool holder.

        Printers without a CFS (or whose Moonraker does not report one) give an
        empty list.
        """
        request = Request(self._url("/printer/objects/query?box&filament_rack"), headers=self._headers())
        status = self._request(request, self._timeout).get("status", {})
        return parse_creality_filaments(status if isinstance(status, Mapping) else {})

    def upload(self, path: Path, folder: str = "", *, start: bool = False) -> UploadResult:
        """Upload ``path`` into ``folder`` of the printer's G-code files.

        An existing file of the same name is replaced. With ``start`` the
        printer starts printing it (or queues it, if Moonraker's job queue is
        on); the result says which happened.
        """
        fields = {"root": "gcodes", "print": "true" if start else "false"}
        if folder:
            fields["path"] = folder
        body = multipart_body(fields, path)
        request = upload_request(self._url("/server/files/upload"), self._headers(), body)
        answer = self._request(request, self._upload_timeout)
        item = answer.get("item")
        if not isinstance(item, dict):
            item = {}
        remote = str(item.get("path") or PurePosixPath(folder, path.name))
        return UploadResult(
            remote_path=remote,
            print_started=bool(answer.get("print_started")),
            print_queued=bool(answer.get("print_queued")),
        )

    def _url(self, endpoint: str) -> str:
        return self._host.url + endpoint

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._host.api_key:
            headers["X-Api-Key"] = self._host.api_key
        return headers

    def _request(self, request: Request, timeout: float) -> dict[str, Any]:
        """Send ``request`` and return its JSON answer (Moonraker's ``result`` when wrapped)."""
        data = send_json(request, timeout, self._host, software="Moonraker", refusal=_refusal)
        if not isinstance(data, dict):
            raise PrinterError(f"{self._host.describe()} gave an unexpected answer.")
        result = data.get("result", data)
        return result if isinstance(result, dict) else {}


def parse_creality_filaments(status: Mapping[str, Any]) -> list[LoadedFilament]:
    """Return the loaded filaments in a Creality printer's ``box`` and ``filament_rack`` status.

    Each CFS unit (``T1`` to ``T4``) has four slots, A to D, each with a
    ``color_value`` (a digit, then ``RRGGBB``) and a ``material_type`` code;
    ``same_material`` names the codes in use. A slot whose ``vender`` is
    ``none`` or ``-1``, or without a colour or material, is empty. The external
    spool holder is ``filament_rack``.
    """
    box = status.get("box")
    box = box if isinstance(box, Mapping) else {}
    names: dict[str, str] = {}
    for group in box.get("same_material") or []:
        if isinstance(group, list) and len(group) >= 4 and isinstance(group[3], str):
            names[str(group[0])] = group[3]
    loaded: list[LoadedFilament] = []
    for unit in range(1, 5):
        values = box.get(f"T{unit}")
        if not isinstance(values, Mapping):
            continue
        colours = _list(values.get("color_value"))
        materials = _list(values.get("material_type"))
        vendors = _list(values.get("vender"))
        for index, letter in enumerate("ABCD"):
            vendor = vendors[index] if index < len(vendors) else "-1"
            colour = _creality_colour(colours[index] if index < len(colours) else "-1")
            material = materials[index] if index < len(materials) else "-1"
            if vendor in ("none", "-1") or colour is None or material in ("-1", ""):
                continue
            loaded.append(LoadedFilament(f"{unit}{letter}", colour, names.get(material, "")))
    rack = status.get("filament_rack")
    if isinstance(rack, Mapping):
        colour = _creality_colour(str(rack.get("color_value", "-1")))
        material = str(rack.get("material_type", "-1"))
        if colour is not None and material not in ("-1", ""):
            loaded.append(LoadedFilament("external", colour, names.get(material, "")))
    return loaded


def _list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _creality_colour(value: str) -> str | None:
    """Return a Creality ``color_value`` (``0RRGGBB``) as ``#RRGGBB``, or None."""
    match = re.fullmatch(r"[0-9A-Fa-f]?([0-9A-Fa-f]{6})", value.strip())
    return f"#{match.group(1).upper()}" if match else None


def _refusal(host: PrinterHost, error: HTTPError, body: Any) -> str:
    """Return why the printer refused a request, using Moonraker's own message when given."""
    details = body.get("error", {}) if isinstance(body, dict) else {}
    message = str(details.get("message", "")) if isinstance(details, dict) else ""
    if error.code in (401, 403):
        return (
            f"{host.describe()} refused access (HTTP {error.code}); set its api_key (or "
            "api_key_env) in the configuration, or allow this computer in Moonraker's "
            "trusted_clients."
        )
    if error.code == 404 and not message:
        return (
            f"{host.describe()} has no Moonraker at that address (HTTP 404); check the "
            "address and port (Moonraker usually listens on port 7125)."
        )
    return f"{host.describe()} refused the request (HTTP {error.code}){': ' + message if message else ''}"
