"""Talk to a printer through Moonraker, the web API of Klipper printers.

Two calls are used: ``GET /server/info`` to check that the printer answers,
and ``POST /server/files/upload`` to store a G-code file in the printer's
``gcodes`` folder, optionally starting it as a print. Files are streamed from
disk, so large G-code is not read into memory. Only the Python standard
library is used. This module does not choose files or decide whether to
start a print; that is the sending service's job.
"""

import json
import mimetypes
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from batchslicer.domain.printers import PrinterHost

_CHUNK_BYTES = 1024 * 1024


class MoonrakerError(Exception):
    """Raised when the printer cannot be reached or refuses a request."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    """What the printer did with one uploaded file."""

    remote_path: str
    """Where the file is on the printer, inside its ``gcodes`` folder."""

    print_started: bool = False
    print_queued: bool = False


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

    def upload(self, path: Path, folder: str = "", *, start: bool = False) -> UploadResult:
        """Upload ``path`` into ``folder`` of the printer's G-code files.

        An existing file of the same name is replaced. With ``start`` the
        printer starts printing it (or queues it, if Moonraker's job queue is
        on); the result says which happened.
        """
        boundary = f"batchslicer-{uuid.uuid4().hex}"
        fields = {"root": "gcodes", "print": "true" if start else "false"}
        if folder:
            fields["path"] = folder
        head = b"".join(
            _part_header(boundary, f'name="{key}"') + value.encode("utf-8") + b"\r\n"
            for key, value in fields.items()
        )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head += _part_header(
            boundary,
            f'name="file"; filename="{_quoted(path.name)}"',
            content_type,
        )
        tail = f"\r\n--{boundary}--\r\n".encode("ascii")
        size = len(head) + path.stat().st_size + len(tail)

        def body() -> Iterator[bytes]:
            yield head
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK_BYTES):
                    yield chunk
            yield tail

        request = Request(
            self._url("/server/files/upload"),
            data=body(),
            method="POST",
            headers={
                **self._headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(size),
            },
        )
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
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only, checked in domain.printers
                data = json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as error:
            raise MoonrakerError(_refusal(self._host, error)) from error
        except (URLError, TimeoutError, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            raise MoonrakerError(f"Cannot reach {self._host.describe()}: {reason}") from error
        except (ValueError, UnicodeDecodeError) as error:
            raise MoonrakerError(
                f"{self._host.describe()} did not answer like Moonraker (is the address "
                "right, including the port?)"
            ) from error
        if not isinstance(data, dict):
            raise MoonrakerError(f"{self._host.describe()} gave an unexpected answer.")
        result = data.get("result", data)
        return result if isinstance(result, dict) else {}


def _part_header(boundary: str, disposition: str, content_type: str | None = None) -> bytes:
    lines = [f"--{boundary}", f"Content-Disposition: form-data; {disposition}"]
    if content_type:
        lines.append(f"Content-Type: {content_type}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def _quoted(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _refusal(host: PrinterHost, error: HTTPError) -> str:
    """Return why the printer refused a request, using Moonraker's own message when given."""
    message = ""
    try:
        data = json.loads(error.read().decode("utf-8"))
        details = data.get("error", {}) if isinstance(data, dict) else {}
        message = str(details.get("message", "")) if isinstance(details, dict) else ""
    except (ValueError, UnicodeDecodeError, OSError):
        pass
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
