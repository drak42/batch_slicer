"""Talk to a printer through Moonraker, the web API of Klipper printers.

Two calls are used: ``GET /server/info`` to check that the printer answers,
and ``POST /server/files/upload`` to store a G-code file in the printer's
``gcodes`` folder, optionally starting it as a print. Files are streamed from
disk, so large G-code is not read into memory. Only the Python standard
library is used. This module does not choose files or decide whether to
start a print; that is the sending service's job.
"""

from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

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


def _refusal(host: PrinterHost, error: HTTPError, body: Any) -> str:
    """Return why the printer refused a request, using Moonraker's own message when given."""
    details = body.get("error", {}) if isinstance(body, dict) else {}
    message = str(details.get("message", "")) if isinstance(details, dict) else ""
    if error.code in (401, 403):
        return (
            f"{host.describe()} refused access (HTTP {error.code}); set its api_key in the "
            "configuration, or allow this computer in Moonraker's trusted_clients."
        )
    if error.code == 404 and not message:
        return (
            f"{host.describe()} has no Moonraker at that address (HTTP 404); check the "
            "address and port (Moonraker usually listens on port 7125)."
        )
    return f"{host.describe()} refused the request (HTTP {error.code}){': ' + message if message else ''}"
