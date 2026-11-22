"""What every printer connection offers, and the pieces they share.

A printer connection (Moonraker, OctoPrint) checks that the printer answers
and uploads G-code into a folder, optionally starting the print. This module
holds the shared result types, the error they raise, the :class:`PrinterClient`
protocol the sending service relies on, and the streamed multipart body both
APIs accept. It does not talk to printers itself.
"""

import json
import mimetypes
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from batchslicer.domain.printers import PrinterHost

_CHUNK_BYTES = 1024 * 1024


class PrinterError(Exception):
    """Raised when the printer cannot be reached or refuses a request."""


@dataclass(frozen=True, slots=True)
class UploadResult:
    """What the printer did with one uploaded file."""

    remote_path: str
    """Where the file is on the printer, inside its G-code folder."""

    print_started: bool = False
    print_queued: bool = False


@dataclass(frozen=True, slots=True)
class PrinterStatus:
    """Whether a printer answers, and what state it is in."""

    state: str
    """The printer's own word for its state, such as ``ready`` or ``Operational``."""

    ready: bool
    """Whether the printer could start a print now."""

    software: str = ""
    """What answered, with its version, such as ``Moonraker v0.9.3``."""

    def note(self) -> str:
        """Return a short remark for a printer that is not ready, or ``""``."""
        if self.ready:
            return ""
        return f" ({self.state}; it can still take files)"


class PrinterClient(Protocol):
    """One printer connection, as the sending service uses it."""

    @property
    def host(self) -> PrinterHost:
        """Return the printer this client talks to."""
        ...

    def status(self) -> PrinterStatus:
        """Return the printer's state; raise :class:`PrinterError` if it does not answer."""
        ...

    def upload(self, path: Path, folder: str = "", *, start: bool = False) -> UploadResult:
        """Upload ``path`` into ``folder``, replacing a file of the same name."""
        ...


@dataclass(frozen=True, slots=True)
class MultipartBody:
    """A ``multipart/form-data`` body whose file part is streamed from disk."""

    content_type: str
    size: int
    head: bytes
    path: Path
    tail: bytes

    def chunks(self) -> Iterator[bytes]:
        """Yield the body in pieces, reading the file a megabyte at a time."""
        yield self.head
        with self.path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_BYTES):
                yield chunk
        yield self.tail


def multipart_body(fields: Mapping[str, str], path: Path) -> MultipartBody:
    """Return a form with ``fields`` followed by ``path`` as the ``file`` part."""
    boundary = f"batchslicer-{uuid.uuid4().hex}"
    head = b"".join(
        _part_header(boundary, f'name="{key}"') + value.encode("utf-8") + b"\r\n"
        for key, value in fields.items()
    )
    file_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head += _part_header(boundary, f'name="file"; filename="{_quoted(path.name)}"', file_type)
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    return MultipartBody(
        content_type=f"multipart/form-data; boundary={boundary}",
        size=len(head) + path.stat().st_size + len(tail),
        head=head,
        path=path,
        tail=tail,
    )


def upload_request(url: str, headers: Mapping[str, str], body: MultipartBody) -> Request:
    """Return a POST request sending ``body`` to ``url``."""
    return Request(
        url,
        data=body.chunks(),
        method="POST",
        headers={**headers, "Content-Type": body.content_type, "Content-Length": str(body.size)},
    )


def form_request(url: str, headers: Mapping[str, str], fields: Mapping[str, str]) -> Request:
    """Return a POST request sending ``fields`` as a form without a file."""
    boundary = f"batchslicer-{uuid.uuid4().hex}"
    data = b"".join(
        _part_header(boundary, f'name="{key}"') + value.encode("utf-8") + b"\r\n"
        for key, value in fields.items()
    ) + f"--{boundary}--\r\n".encode("ascii")
    return Request(
        url,
        data=data,
        method="POST",
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def send_json(
    request: Request,
    timeout: float,
    host: PrinterHost,
    *,
    software: str,
    refusal: "RefusalExplainer",
) -> Any:
    """Send ``request`` and return its JSON answer.

    ``software`` names what should answer (for "did not answer like ...");
    ``refusal`` turns an HTTP error into the message raised.
    """
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only, checked in domain.printers
            text = response.read().decode("utf-8")
    except HTTPError as error:
        raise PrinterError(refusal(host, error, _error_body(error))) from error
    except (URLError, TimeoutError, ConnectionError) as error:
        reason = getattr(error, "reason", error)
        raise PrinterError(f"Cannot reach {host.describe()}: {reason}") from error
    except UnicodeDecodeError as error:
        raise PrinterError(_not_like(host, software)) from error
    try:
        return json.loads(text or "{}")
    except ValueError as error:
        raise PrinterError(_not_like(host, software)) from error


class RefusalExplainer(Protocol):
    """Turns an HTTP error from a printer into a message for the user."""

    def __call__(self, host: PrinterHost, error: HTTPError, body: Any) -> str:
        """Return the message; ``body`` is the error's JSON answer, or None."""
        ...


def _error_body(error: HTTPError) -> Any:
    """Return an HTTP error's JSON body, or None if it has none."""
    try:
        return json.loads(error.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError, OSError):
        return None


def _not_like(host: PrinterHost, software: str) -> str:
    return (
        f"{host.describe()} did not answer like {software} (is the address right, "
        "including the port?)"
    )


def _part_header(boundary: str, disposition: str, content_type: str | None = None) -> bytes:
    lines = [f"--{boundary}", f"Content-Disposition: form-data; {disposition}"]
    if content_type:
        lines.append(f"Content-Type: {content_type}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")


def _quoted(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
