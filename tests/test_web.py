"""Tests for the web page and ``batchslicer web``."""

import json
import socket
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from batchslicer.cli import web as web_command  # noqa: E402
from batchslicer.cli.arguments import parse_arguments  # noqa: E402
from batchslicer.cli.web import WebOptions, run_web  # noqa: E402
from batchslicer.services.thumbnails import add_thumbnails  # noqa: E402
from batchslicer.services.watch_status import StatusWriter  # noqa: E402
from batchslicer.web.app import WebSettings, create_app  # noqa: E402
from conftest import write_config  # noqa: E402

_GCODE = "\n".join(
    ["; HEADER_BLOCK_START", "; HEADER_BLOCK_END", "M83", ";TYPE:Outer wall"]
    + [f"G1 Z{0.2 * (n + 1):.1f}\nG1 X100 Y100\nG1 X120 Y100 E.5\nG1 X120 Y110 E.5" for n in range(5)]
    + ["; filament_colour = #F2754E", "; thumbnails = 96x96/PNG"]
) + "\n"


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    """A watched folder with two waiting drops, and an output folder with one finished run."""
    watched, output = tmp_path / "in", tmp_path / "out"
    (watched / "kit").mkdir(parents=True)
    (watched / "kit" / "a.stl").write_text("solid")
    (watched / "cube.stl").write_text("solid")
    (watched / "notes.txt").write_text("not a model")
    run = output / "bracket set-20261124-100000"
    (run / "bracket").mkdir(parents=True)
    gcode = run / "bracket" / "bracket.gcode"
    gcode.write_text(_GCODE)
    add_thumbnails(gcode)
    rows = [
        {"model": "bracket.stl", "status": "ok", "gcode": ["bracket/bracket.gcode"], "print_time": "1h 4m",
         "print_seconds": 3840, "filament_g": 40.8, "filament_g_each": [30.1, 10.7], "filament_changes": 12},
        {"model": "broken <b>.stl", "status": "failed", "gcode": [], "message": "Nothing to be sliced"},
    ]
    (run / "report.json").write_text(json.dumps({"models": rows}))
    return watched, output


def _client(folders: tuple[Path, Path]) -> TestClient:
    watched, output = folders
    return TestClient(create_app(WebSettings(watched=watched, output=output)), base_url="http://127.0.0.1:8765")


def test_the_page_shows_the_queue_and_the_results(folders: tuple[Path, Path]) -> None:
    """Waiting drops, what is being sliced, and the finished runs with their totals."""
    watched, output = folders
    writer = StatusWriter(watched, output)
    writer.finished("earlier.stl", success=False)
    writer.slicing("kit")
    writer.progress(2, 3, "a.stl")

    page = _client(folders).get("/")

    assert page.status_code == 200
    assert "Slicing <strong>kit</strong>" in page.text
    assert "model 2 of 3: a.stl" in page.text
    assert "<li>cube.stl</li>" in page.text and "<li>kit</li>" not in page.text  # kit is being sliced
    assert "notes.txt" not in page.text
    assert "earlier.stl" in page.text
    assert "bracket set-20261124-100000" in page.text
    assert 'href="/results/bracket%20set-20261124-100000"' in page.text
    assert "1 sliced" in page.text and "1 failed" in page.text and "41 g" in page.text


def test_before_the_watcher_starts_the_page_says_so(folders: tuple[Path, Path]) -> None:
    """Without a status file the queue says it is waiting for the watcher."""
    assert "Waiting for the watcher to start" in _client(folders).get("/queue").text


def test_a_result_shows_each_model(folders: tuple[Path, Path]) -> None:
    """Print time, filament per slot, changes, and failures with the slicer's reason, escaped."""
    page = _client(folders).get("/results/bracket set-20261124-100000")

    assert page.status_code == 200
    assert "1h 4m" in page.text
    assert "slot 1: 30 g, slot 2: 11 g" in page.text
    assert "Nothing to be sliced" in page.text
    assert "broken &lt;b&gt;.stl" in page.text
    assert _client(folders).get("/results/nothing-here").status_code == 404


def test_preview_pictures_come_from_the_gcode(folders: tuple[Path, Path]) -> None:
    """The picture in the G-code is served as PNG; paths outside the output folder are refused."""
    client = _client(folders)
    picture = client.get("/preview/bracket%20set-20261124-100000/bracket/bracket.gcode")
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/png"
    assert picture.content.startswith(b"\x89PNG")

    folders[0].joinpath("secret.gcode").write_text(_GCODE)
    assert client.get("/preview/../in/secret.gcode").status_code == 404
    assert client.get("/preview/%2E%2E/in/secret.gcode").status_code == 404
    assert client.get("/preview/bracket%20set-20261124-100000/report.json").status_code == 404


def test_only_this_computers_names_are_answered(folders: tuple[Path, Path]) -> None:
    """Other host names (DNS rebinding) are refused; pages carry protective headers."""
    watched, output = folders
    app = create_app(WebSettings(watched=watched, output=output))
    assert TestClient(app, base_url="http://evil.example").get("/").status_code == 400
    assert TestClient(app, base_url="http://localhost:8765").get("/").status_code == 200
    page = _client(folders).get("/")
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_the_page_ships_its_own_htmx(folders: tuple[Path, Path]) -> None:
    """htmx is served from the package, not downloaded."""
    script = _client(folders).get("/static/htmx.min.js")
    assert script.status_code == 200 and "htmx" in script.text


# --- batchslicer web -----------------------------------------------------------


def test_web_takes_watch_run_options() -> None:
    """--port is the page's; everything else is for the watch run, which gets --watch once."""
    options = parse_arguments(["web", "--profile", "k2 pla", "--port", "9000", "--input", "drop", "--watch"])
    assert options == WebOptions(port=9000, run_arguments=("--profile", "k2 pla", "--input", "drop"),
                                 input=Path("drop"))
    assert parse_arguments(["web", "--port=9001"]) == WebOptions(port=9001)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [(["--port", "80"], "1024 to 65535"), (["--start"], "--start cannot be used with --watch"),
     (["--port"], "--port needs a number")],
)
def test_web_refuses_bad_options(arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Mistakes exit with status 2 and say what is wrong."""
    with pytest.raises(SystemExit) as stopped:
        parse_arguments(["web", *arguments])
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err


def test_without_the_web_extra_it_says_how_to_add_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing Starlette and the rest: nothing runs, and the install command is shown."""
    monkeypatch.setattr(web_command, "missing_modules", lambda: ["starlette"])
    lines: list[str] = []
    assert run_web(WebOptions(), run=lambda _: pytest.fail("must not run"), write=lines.append) == 1
    assert 'pipx install --force "batchslicer[web]"' in lines[0]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_web_serves_the_page_while_the_watch_runs(tmp_path: Path) -> None:
    """The page answers on 127.0.0.1 while the watch runs, and stops with it."""
    write_config(tmp_path / "bs", {"paths": {"incoming": tmp_path / "in", "output": tmp_path / "out"}})
    port = _free_port()
    seen: list[str] = []

    def run(arguments: Sequence[str]) -> int:
        seen.extend(arguments)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=10) as response:
            seen.append(response.read().decode())
        return 0

    options = WebOptions(port=port, run_arguments=("--profile", "k2"), config=tmp_path / "bs" / "config.yaml")
    lines: list[str] = []
    assert run_web(options, run=run, write=lines.append) == 0
    assert seen[:3] == ["--profile", "k2", "--watch"]
    assert str(tmp_path / "in") in seen[3]
    assert lines == [f"Web page: http://127.0.0.1:{port}  (on this computer only)"]
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)


def test_a_port_in_use_is_explained(tmp_path: Path) -> None:
    """If the port is taken, nothing runs and --port is suggested."""
    write_config(tmp_path / "bs", {"paths": {"incoming": tmp_path / "in"}})
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        lines: list[str] = []
        options = WebOptions(port=port, config=tmp_path / "bs" / "config.yaml")
        assert run_web(options, run=lambda _: pytest.fail("must not run"), write=lines.append) == 1
    assert "--port" in lines[0]
