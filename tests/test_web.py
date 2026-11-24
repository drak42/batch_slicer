"""Tests for the web page and ``batchslicer web``."""

import io
import json
import re
import socket
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from batchslicer.cli import web as web_command  # noqa: E402
from batchslicer.cli.arguments import parse_arguments  # noqa: E402
from batchslicer.cli.web import WebOptions, run_web  # noqa: E402
from batchslicer.domain.printers import PrinterHost  # noqa: E402
from batchslicer.services.thumbnails import add_thumbnails  # noqa: E402
from batchslicer.services.watch_status import StatusWriter  # noqa: E402
from batchslicer.web import app as web_app  # noqa: E402
from batchslicer.web.app import DropTarget, WebSettings, create_app  # noqa: E402
from conftest import FakeMoonraker, write_config  # noqa: E402

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


# --- upload and download ---------------------------------------------------------


def _token(client: TestClient) -> str:
    match = re.search(r'name="batchslicer-token" content="([^"]+)"', client.get("/").text)
    assert match is not None
    return match.group(1)


def _files(*pairs: tuple[str, bytes]) -> tuple[dict[str, list[str]], list[tuple[str, tuple[str, bytes]]]]:
    return {"path": [name for name, _ in pairs]}, [("file", (name.rpartition("/")[2], data)) for name, data in pairs]


def test_uploads_go_into_the_watched_folder(folders: tuple[Path, Path]) -> None:
    """Files and folders keep their shape; other files are skipped; ../ cannot escape."""
    watched = folders[0]
    client = _client(folders)
    data, files = _files(("cube.stl", b"solid"), ("set/a.stl", b"solid"), ("set/notes.txt", b"x"),
                         ("../../escape.stl", b"solid"))

    answer = client.post("/upload", data=data, files=files, headers={"x-batchslicer-token": _token(client)})

    assert answer.status_code == 200
    assert answer.json() == {"added": ["cube (2).stl", "escape.stl", "set"], "skipped": ["set/notes.txt"]}
    assert (watched / "set" / "a.stl").read_bytes() == b"solid"
    assert (watched / "escape.stl").is_file() and not (watched.parent.parent / "escape.stl").exists()
    assert not list(watched.glob(".batchslicer-upload-*"))
    assert "cube (2).stl" in client.get("/queue").text


@pytest.mark.parametrize(
    "headers",
    [{}, {"x-batchslicer-token": "wrong"}, {"origin": "http://evil.example"}, {"sec-fetch-site": "cross-site"}],
)
def test_uploads_from_elsewhere_are_refused(folders: tuple[Path, Path], headers: dict[str, str]) -> None:
    """Without the page's token, or from another website, nothing is stored."""
    client = _client(folders)
    full = {"x-batchslicer-token": _token(client), **headers} if headers and "x-batchslicer-token" not in headers else headers
    data, files = _files(("sneaky.stl", b"solid"))
    assert client.post("/upload", data=data, files=files, headers=full).status_code == 403
    assert not (folders[0] / "sneaky.stl").exists()


def test_uploads_that_are_too_large_are_refused(folders: tuple[Path, Path]) -> None:
    """The size the request announces is checked before anything is read."""
    client = _client(folders)
    data, files = _files(("cube.stl", b"solid"))
    headers = {"x-batchslicer-token": _token(client), "content-length": str(50 * 1024**3)}
    answer = client.post("/upload", data=data, files=files, headers=headers)
    assert answer.status_code == 413 and "Too large" in answer.json()["error"]


def test_gcode_and_reports_can_be_downloaded(folders: tuple[Path, Path]) -> None:
    """One file at a time, only G-code and reports, only from the output folder."""
    client = _client(folders)
    run = "bracket%20set-20261124-100000"
    gcode = client.get(f"/download/{run}/bracket/bracket.gcode")
    assert gcode.status_code == 200
    assert "attachment" in gcode.headers["content-disposition"] and "bracket.gcode" in gcode.headers["content-disposition"]
    assert gcode.text.startswith("; HEADER_BLOCK_START")
    assert client.get(f"/download/{run}/report.json").json()["models"][0]["model"] == "bracket.stl"
    (folders[1] / "bracket set-20261124-100000" / "secret.txt").write_text("no")
    assert client.get(f"/download/{run}/secret.txt").status_code == 404
    assert client.get(f"/download/{run}/../../in/cube.stl").status_code == 404


def test_a_run_downloads_as_a_zip(folders: tuple[Path, Path]) -> None:
    """The ZIP holds the run's G-code and report in a folder named after the run."""
    answer = _client(folders).get("/zip/bracket%20set-20261124-100000")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(answer.content)).namelist()
    assert names == ["bracket set-20261124-100000/bracket/bracket.gcode", "bracket set-20261124-100000/report.json"]
    assert _client(folders).get("/zip/../in").status_code == 404


# --- printers and sending ------------------------------------------------------


def _printing_client(folders: tuple[Path, Path], fake: FakeMoonraker | None) -> TestClient:
    watched, output = folders
    printers = {"k2plus": PrinterHost("k2plus", fake.url)} if fake is not None else {}
    app = create_app(WebSettings(watched=watched, output=output, printers=printers))
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_the_printers_page_shows_each_printer_and_its_cfs(
    folders: tuple[Path, Path], fake_moonraker: FakeMoonraker
) -> None:
    """Each card asks its printer: state, software, and every loaded filament with a swatch."""
    from test_filaments import K2_STATUS

    fake_moonraker.objects = K2_STATUS
    client = _printing_client(folders, fake_moonraker)
    page = client.get("/printers")
    assert page.status_code == 200 and 'hx-get="/printers/k2plus"' in page.text

    card = client.get("/printers/k2plus").text
    assert "ready" in card
    assert card.count('class="swatch"') == 3
    assert 'fill="#' in card
    assert client.get("/printers/unknown").status_code == 404


def test_a_printer_that_does_not_answer_says_so(folders: tuple[Path, Path]) -> None:
    """An address nothing listens on is reported, not an error page."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    watched, output = folders
    app = create_app(WebSettings(watched=watched, output=output,
                                 printers={"gone": PrinterHost("gone", f"http://127.0.0.1:{port}")}))
    card = TestClient(app, base_url="http://127.0.0.1:8765").get("/printers/gone")
    assert card.status_code == 200 and "Not answering" in card.text


def test_without_printers_the_page_says_how_to_add_them(folders: tuple[Path, Path]) -> None:
    """No printers section: the printers page and the result page explain."""
    client = _printing_client(folders, None)
    assert "No printers are configured" in client.get("/printers").text
    result = client.get("/results/bracket%20set-20261124-100000").text
    assert "add your printers" in result and "<select" not in result


def test_a_run_is_sent_to_a_printer(folders: tuple[Path, Path], fake_moonraker: FakeMoonraker) -> None:
    """The run's G-code goes into a folder named after it; nothing is started."""
    client = _printing_client(folders, fake_moonraker)
    assert '<option value="k2plus">' in client.get("/results/bracket%20set-20261124-100000").text

    answer = client.post("/send", data={"run": "bracket set-20261124-100000", "printer": "k2plus"},
                         headers={"x-batchslicer-token": _token(client)})

    assert answer.status_code == 200
    assert "Sent 1 of 1 file" in answer.text
    assert list(fake_moonraker.files) == ["bracket set-20261124-100000/bracket.gcode"]
    assert all(form.get("print") != "true" for form in fake_moonraker.forms)


def test_sending_needs_the_page_and_a_configured_printer(
    folders: tuple[Path, Path], fake_moonraker: FakeMoonraker
) -> None:
    """Without the token nothing is sent; unknown printers and runs are refused."""
    client = _printing_client(folders, fake_moonraker)
    run = "bracket set-20261124-100000"
    assert client.post("/send", data={"run": run, "printer": "k2plus"}).status_code == 403
    token = {"x-batchslicer-token": _token(client)}
    assert client.post("/send", data={"run": run, "printer": "other"}, headers=token).status_code == 400
    assert client.post("/send", data={"run": "../x", "printer": "k2plus"}, headers=token).status_code == 400
    assert fake_moonraker.files == {}


# --- other watched folders and the About page -------------------------------------


def _with_service(folders: tuple[Path, Path], tmp_path: Path) -> TestClient:
    watched, output = folders
    settings = WebSettings(watched=watched, output=output, config=tmp_path / "config.yaml",
                           run_arguments=("--profile", "k2 pla"),
                           targets=(DropTarget("ender", tmp_path / "ender-drop"),))
    return TestClient(create_app(settings), base_url="http://127.0.0.1:8765")


def test_uploads_can_go_to_a_services_folder(folders: tuple[Path, Path], tmp_path: Path) -> None:
    """The page offers each service's folder; an unknown one is refused."""
    (tmp_path / "ender-drop").mkdir()
    client = _with_service(folders, tmp_path)
    assert '<option value="ender">' in client.get("/").text
    token = {"x-batchslicer-token": _token(client)}
    data, files = _files(("bolt.stl", b"solid"))

    answer = client.post("/upload", data={**data, "target": "ender"}, files=files, headers=token)
    assert answer.status_code == 200 and (tmp_path / "ender-drop" / "bolt.stl").is_file()
    assert not (folders[0] / "bolt.stl").exists()
    assert client.post("/upload", data={**data, "target": "nope"}, files=files, headers=token).status_code == 400


def test_the_queue_shows_what_services_are_doing(folders: tuple[Path, Path], tmp_path: Path) -> None:
    """Each service's folder: its state from its status file and how much waits."""
    (tmp_path / "ender-drop").mkdir()
    (tmp_path / "ender-drop" / "a.stl").write_text("solid")
    StatusWriter(tmp_path / "ender-drop", tmp_path / "out").slicing("kit")
    queue = _with_service(folders, tmp_path).get("/queue").text
    assert "Watched by services" in queue and "slicing kit" in queue and "1 waiting" in queue


def test_the_about_page_and_doctor(folders: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """About shows the settings; doctor runs only from the page, and its report is shown."""
    def fake_doctor(options: object, *, write: object) -> int:
        write(f"checked {options.config}")  # type: ignore[attr-defined, operator]
        return 1

    monkeypatch.setattr(web_app, "run_doctor", fake_doctor)
    client = _with_service(folders, tmp_path)
    about = client.get("/about").text
    assert "batchslicer web --profile &#39;k2 pla&#39;" in about
    assert str(tmp_path / "config.yaml") in about and "Service ender" in about

    assert client.post("/about/doctor").status_code == 403
    report = client.post("/about/doctor", headers={"x-batchslicer-token": _token(client)}).text
    assert "1 problem found." in report and f"checked {tmp_path / 'config.yaml'}" in report


def test_services_already_shown_are_not_offered_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A service watching the page's own folder is not a second target."""
    write_config(tmp_path / "bs", {"paths": {"incoming": tmp_path / "in"}})
    monkeypatch.setattr(web_command, "_service_folders",
                        lambda: [("watch", tmp_path / "in"), ("ender", tmp_path / "ender")])
    settings = web_command._settings(WebOptions(config=tmp_path / "bs" / "config.yaml"))
    assert settings.targets == (DropTarget("ender", tmp_path / "ender"),)
    assert settings.config == (tmp_path / "bs" / "config.yaml").absolute()


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


def test_web_serves_the_page_while_the_watch_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page answers on 127.0.0.1 while the watch runs, and stops with it."""
    monkeypatch.setattr(web_command, "_service_folders", lambda: [])
    write_config(tmp_path / "bs", {"paths": {"incoming": tmp_path / "in", "output": tmp_path / "out"}})
    config_file = tmp_path / "bs" / "config.yaml"
    config_file.write_text(config_file.read_text() + "printers:\n  k2plus:\n    url: http://192.0.2.1:7125\n")
    port = _free_port()
    seen: list[str] = []

    def run(arguments: Sequence[str]) -> int:
        seen.extend(arguments)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=10) as response:
            seen.append(response.read().decode())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/printers", timeout=10) as response:
            seen.append(response.read().decode())
        return 0

    options = WebOptions(port=port, run_arguments=("--profile", "k2"), config=tmp_path / "bs" / "config.yaml")
    lines: list[str] = []
    assert run_web(options, run=run, write=lines.append) == 0
    assert seen[:3] == ["--profile", "k2", "--watch"]
    assert str(tmp_path / "in") in seen[3]
    assert 'hx-get="/printers/k2plus"' in seen[4]  # the configured printers are on the page
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
