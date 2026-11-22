"""Shared test helpers."""

import json
import os
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from batchslicer.backends import detection
from batchslicer.core import locations
from batchslicer.core.config import Config


def set_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Make ``home`` the home folder: HOME on Linux and macOS, USERPROFILE on Windows."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def fake_program(path: Path, output: str = "", *, exit_code: int = 0, stderr: str = "") -> Path:
    """Write a stand-in program that prints ``output`` (and ``stderr``) and exits with ``exit_code``.

    It is a small Python script: run directly on Linux and macOS, and through
    a ``.cmd`` file on Windows (the path returned then ends in ``.cmd``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import sys\n"
        f"sys.stdout.write({output!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({exit_code})\n"
    )
    if os.name == "nt":
        script = path.with_name(path.name + ".py")
        script.write_text(code, encoding="utf-8")
        program = path.with_name(path.name + ".cmd")
        program.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return program
    path.write_text(f"#!{sys.executable}\n{code}", encoding="utf-8")
    path.chmod(0o755)
    return path


def write_config(directory: Path, sections: dict[str, dict[str, object]]) -> Config:
    """Write ``sections`` as a configuration file in ``directory`` and return it loaded.

    Path values are written as strings, so relative paths are relative to
    ``directory``, exactly as for a real configuration file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    data = {
        section: {key: str(value) for key, value in values.items()}
        for section, values in sections.items()
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = Config(path)
    config.load()
    return config



@pytest.fixture(autouse=True)
def _isolate_user_folders(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep BatchSlicer's default log and cache folders out of the real home folder."""
    base = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_STATE_HOME", str(base / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(base / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(base / "data"))


@dataclass
class FakeMoonraker:
    """A stand-in for a printer's Moonraker, recording what it is sent."""

    url: str
    files: dict[str, bytes] = field(default_factory=dict)
    """Uploaded files by their path in the printer's G-code folder."""

    forms: list[dict[str, str]] = field(default_factory=list)
    """The form fields of each upload, in order."""

    api_key: str = ""
    """When set, requests without this X-Api-Key are refused with 401."""

    busy: bool = False
    """When set, a print asked for is not started."""

    fail_names: set[str] = field(default_factory=set)
    """File names whose upload is refused with an error."""

    klippy_state: str = "ready"
    objects: dict[str, object] = field(default_factory=dict)
    """Printer objects reported by /printer/objects/query, such as a CFS ``box``."""


@pytest.fixture
def fake_moonraker() -> Iterator[FakeMoonraker]:
    """Run a stand-in Moonraker on a free local port for the duration of a test."""
    state = FakeMoonraker(url="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, status: int, data: object) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:
            if state.api_key and self.headers.get("X-Api-Key") != state.api_key:
                self._send(401, {"error": {"code": 401, "message": "Unauthorized"}})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            if not self._allowed():
                return
            if self.path == "/server/info":
                self._send(200, {"result": {"klippy_state": state.klippy_state, "moonraker_version": "v0.9.3"}})
            elif self.path.startswith("/printer/objects/query"):
                self._send(200, {"result": {"status": state.objects, "eventtime": 1.0}})
            else:
                self._send(404, {"error": {"code": 404, "message": "Not Found"}})

        def do_POST(self) -> None:  # noqa: N802 - http.server's naming
            if not self._allowed():
                return
            if self.path != "/server/files/upload":
                self._send(404, {"error": {"code": 404, "message": "Not Found"}})
                return
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=default).parsebytes(
                f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body
            )
            form: dict[str, str] = {}
            content = b""
            filename = ""
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "file":
                    filename = part.get_filename() or ""
                    content = part.get_payload(decode=True) or b""
                else:
                    form[str(name)] = part.get_content().strip()
            state.forms.append(form)
            if filename in state.fail_names:
                self._send(400, {"error": {"code": 400, "message": f"Bad file {filename}"}})
                return
            path = f"{form['path']}/{filename}" if form.get("path") else filename
            state.files[path] = content
            start = form.get("print") == "true"
            self._send(201, {
                "result": {
                    "item": {"path": path, "root": "gcodes"},
                    "print_started": start and not state.busy,
                    "print_queued": False,
                    "action": "create_file",
                }
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@dataclass
class FakeOctoPrint:
    """A stand-in for OctoPrint, recording what it is sent."""

    url: str
    api_key: str = "octo-key"
    """Requests without this X-Api-Key are refused with 403, as OctoPrint does."""

    files: dict[str, bytes] = field(default_factory=dict)
    """Uploaded files by their path in OctoPrint's local storage."""

    folders: set[str] = field(default_factory=set)
    """Folders that exist; uploads into a missing folder fail with 404."""

    forms: list[dict[str, str]] = field(default_factory=list)
    """The form fields of each file upload, in order."""

    printer_state: str = "Operational"
    printing: str = ""
    """The path of the file being printed, which cannot be replaced."""

    fail_names: set[str] = field(default_factory=set)
    """File names whose upload is refused with an error."""


def _read_form(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], str, bytes]:
    """Return a multipart request's fields, file name and file content."""
    body = handler.rfile.read(int(handler.headers["Content-Length"]))
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {handler.headers['Content-Type']}\r\n\r\n".encode() + body
    )
    form: dict[str, str] = {}
    filename, content = "", b""
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name == "file":
            filename = part.get_filename() or ""
            content = part.get_payload(decode=True) or b""
        else:
            form[str(name)] = part.get_content().strip()
    return form, filename, content


@pytest.fixture
def fake_octoprint() -> Iterator[FakeOctoPrint]:
    """Run a stand-in OctoPrint on a free local port for the duration of a test."""
    state = FakeOctoPrint(url="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, status: int, data: object) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:
            if self.headers.get("X-Api-Key") != state.api_key:
                self._send(403, {"error": "You don't have the permission to access the requested resource."})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            if not self._allowed():
                return
            if self.path == "/api/version":
                self._send(200, {"api": "0.1", "server": "1.10.3", "text": "OctoPrint 1.10.3"})
            elif self.path == "/api/connection":
                self._send(200, {"current": {"state": state.printer_state, "port": "/dev/ttyUSB0"}})
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802 - http.server's naming
            if not self._allowed():
                return
            if self.path != "/api/files/local":
                self._send(404, {"error": "Not found"})
                return
            form, filename, content = _read_form(self)
            parent = form.get("path", "")
            if parent and parent not in state.folders:
                self._send(404, {"error": f"No such folder: {parent}"})
                return
            if "foldername" in form:
                folder = f"{parent}/{form['foldername']}" if parent else form["foldername"]
                if folder in state.folders:
                    self._send(409, {"error": "Folder already exists"})
                    return
                state.folders.add(folder)
                self._send(201, {"folder": {"name": form["foldername"], "path": folder}, "done": True})
                return
            state.forms.append(form)
            path = f"{parent}/{filename}" if parent else filename
            if filename in state.fail_names:
                self._send(415, {"error": f"Could not upload the file {filename}"})
                return
            if path == state.printing:
                self._send(409, {"error": "Trying to overwrite file that is currently being printed"})
                return
            state.files[path] = content
            printing = form.get("print") == "true" and state.printer_state == "Operational"
            if printing:
                state.printing = path
            self._send(201, {
                "files": {"local": {"name": filename, "path": path, "origin": "local"}},
                "done": True,
                "effectiveSelect": form.get("select") == "true" and printing,
                "effectivePrint": printing,
            })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def linux_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the Linux folder layout whatever system runs the tests.

    Tests of the Windows or macOS layout switch it on with the ``windows`` or
    ``macos`` fixture.
    """
    monkeypatch.setattr(detection, "is_windows", lambda: False)
    monkeypatch.setattr(locations, "is_windows", lambda: False)
    monkeypatch.setattr(detection, "is_macos", lambda: False)


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the Windows folder layout (Program Files, %APPDATA%, %LOCALAPPDATA%)."""
    monkeypatch.setattr(detection, "is_windows", lambda: True)
    monkeypatch.setattr(locations, "is_windows", lambda: True)


@pytest.fixture
def macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detect slicers as on macOS."""
    monkeypatch.setattr(detection, "is_macos", lambda: True)
