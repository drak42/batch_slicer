"""Shared test helpers."""

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from batchslicer.core.config import Config


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
