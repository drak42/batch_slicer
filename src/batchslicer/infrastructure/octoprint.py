"""Talk to a printer through OctoPrint's REST API.

``GET /api/version`` checks that OctoPrint answers and accepts the API key,
``GET /api/connection`` gives the printer's state, and
``POST /api/files/local`` creates folders and uploads G-code, optionally
selecting and printing it. Every request carries the ``X-Api-Key`` header;
OctoPrint always asks for one. Files are streamed from disk. This module does
not choose files or decide whether to start a print; that is the sending
service's job.
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
    form_request,
    multipart_body,
    send_json,
    upload_request,
)

_READY_STATE = "Operational"
"""OctoPrint's state for a connected printer that is not printing."""


class OctoPrintClient:
    """Send requests to one printer's OctoPrint."""

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
        self._folders: set[str] = set()

    @property
    def host(self) -> PrinterHost:
        """Return the printer this client talks to."""
        return self._host

    def status(self) -> PrinterStatus:
        """Return the printer's connection state; it is ready when ``Operational``."""
        version = self._get("/api/version")
        if not isinstance(version, dict) or "server" not in version:
            raise PrinterError(
                f"{self._host.describe()} did not answer like OctoPrint (is the address "
                "right, including the port?)"
            )
        connection = self._get("/api/connection")
        current = connection.get("current", {}) if isinstance(connection, dict) else {}
        state = str(current.get("state", "") if isinstance(current, dict) else "") or "unknown"
        return PrinterStatus(
            state=f"printer is {state}",
            ready=state == _READY_STATE,
            software=f"OctoPrint {version.get('server', '')}".strip(),
        )

    def upload(self, path: Path, folder: str = "", *, start: bool = False) -> UploadResult:
        """Upload ``path`` into ``folder`` of OctoPrint's local files.

        Missing folders are created first. An existing file of the same name is
        replaced, unless it is being printed. With ``start`` OctoPrint selects
        and prints the file if the printer is ready; the result says whether it
        did.
        """
        self._make_folders(folder)
        fields = {"select": "true" if start else "false", "print": "true" if start else "false"}
        if folder:
            fields["path"] = folder
        body = multipart_body(fields, path)
        request = upload_request(self._url("/api/files/local"), self._headers(), body)
        answer = self._send(request, self._upload_timeout)
        files = answer.get("files", {}) if isinstance(answer, dict) else {}
        local = files.get("local", {}) if isinstance(files, dict) else {}
        remote = local.get("path") if isinstance(local, dict) else None
        return UploadResult(
            remote_path=str(remote or PurePosixPath(folder, path.name)),
            print_started=bool(answer.get("effectivePrint")) if isinstance(answer, dict) else False,
        )

    def _make_folders(self, folder: str) -> None:
        """Create ``folder`` and its parents on OctoPrint, if not done already."""
        parent = ""
        for name in PurePosixPath(folder).parts if folder else ():
            current = f"{parent}/{name}" if parent else name
            if current not in self._folders:
                fields = {"foldername": name, "path": parent}
                request = form_request(self._url("/api/files/local"), self._headers(), fields)
                try:
                    self._send(request, self._timeout)
                except PrinterError as error:
                    if not isinstance(error.__cause__, HTTPError) or error.__cause__.code != 409:
                        raise  # 409: the folder is already there
                self._folders.add(current)
            parent = current

    def _get(self, endpoint: str) -> Any:
        return self._send(Request(self._url(endpoint), headers=self._headers()), self._timeout)

    def _send(self, request: Request, timeout: float) -> Any:
        return send_json(request, timeout, self._host, software="OctoPrint", refusal=_refusal)

    def _url(self, endpoint: str) -> str:
        return self._host.url + endpoint

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "X-Api-Key": self._host.api_key}


def _refusal(host: PrinterHost, error: HTTPError, body: Any) -> str:
    """Return why OctoPrint refused a request, using its own message when given."""
    message = body.get("error", "") if isinstance(body, dict) else ""
    message = message if isinstance(message, str) else ""
    if error.code in (401, 403):
        return (
            f"{host.describe()} refused access (HTTP {error.code}); check its api_key in "
            "the configuration (OctoPrint: Settings > Application Keys)."
        )
    if error.code == 404 and not message:
        return (
            f"{host.describe()} has no OctoPrint at that address (HTTP 404); check the "
            "address and port."
        )
    if error.code == 409 and not message:
        message = "the file is being printed, or the printer is busy"
    return f"{host.describe()} refused the request (HTTP {error.code}){': ' + message if message else ''}"
