"""Tests for sending G-code to printers: configuration, Moonraker and the sending service."""

import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.domain.printers import (
    OCTOPRINT,
    PrinterHost,
    PrinterHostError,
    host_from_address,
    printer_hosts,
)
from batchslicer.infrastructure.moonraker import MoonrakerClient, MoonrakerError
from batchslicer.infrastructure.octoprint import OctoPrintClient
from batchslicer.infrastructure.printer_api import PrinterError
from batchslicer.infrastructure.printer_clients import client_for
from batchslicer.services.sending import SendingService, Upload, plan_uploads
from batchslicer.services.slicing import SliceOutcome
from conftest import FakeMoonraker, FakeOctoPrint

# --- configuration ---------------------------------------------------------


def test_printers_are_read_from_the_configuration() -> None:
    """Names map to addresses; a missing scheme means http and a trailing / is dropped."""
    hosts = printer_hosts({
        "k2plus": {"url": "192.168.1.50:7125/"},
        "voron": {"url": "https://voron.local", "api_key": "secret"},
    })

    assert hosts == {
        "k2plus": PrinterHost("k2plus", "http://192.168.1.50:7125"),
        "voron": PrinterHost("voron", "https://voron.local", "secret"),
    }


@pytest.mark.parametrize("section", [None, "", {}])
def test_no_printers_section_means_no_printers(section: object) -> None:
    """An empty or missing section is fine."""
    assert printer_hosts(section) == {}


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ({"k2": {}}, "url is missing"),
        ({"k2": "http://x"}, "must have a url"),
        ({"k2": {"url": "ftp://x"}}, "not a web address"),
        ({"k2": {"url": "http://x", "port": 1}}, "unknown settings: port"),
        ({"bad name!": {"url": "http://x"}}, "printer names"),
        ({"k2": {"url": "http://x", "api_key": 5}}, "api_key must be text"),
        ({"k2": {"url": "http://x", "type": "bambu"}}, "type must be moonraker or octoprint"),
        ({"ender": {"url": "http://x", "type": "octoprint"}}, "OctoPrint needs an api_key"),
        (["k2"], "must map printer names"),
    ],
)
def test_unusable_printer_settings_are_explained(section: object, message: str) -> None:
    """Each mistake names the printer and what to fix."""
    with pytest.raises(PrinterHostError, match=message):
        printer_hosts(section)


def test_octoprint_printers_are_read_from_the_configuration() -> None:
    """type: octoprint (in any case) gives an OctoPrint printer, shown as such."""
    hosts = printer_hosts({"ender": {"type": "OctoPrint", "url": "octopi.local", "api_key": "k"}})

    assert hosts == {"ender": PrinterHost("ender", "http://octopi.local", "k", OCTOPRINT)}
    assert hosts["ender"].describe() == "ender (OctoPrint, http://octopi.local)"
    assert isinstance(client_for(hosts["ender"]), OctoPrintClient)
    assert isinstance(client_for(PrinterHost("k2", "http://k2:7125")), MoonrakerClient)


# --- Moonraker -------------------------------------------------------------


def _client(fake: FakeMoonraker, api_key: str = "") -> MoonrakerClient:
    return MoonrakerClient(PrinterHost("k2", fake.url, api_key), timeout_seconds=5)


def test_server_info_is_read(fake_moonraker: FakeMoonraker) -> None:
    """Moonraker's wrapped answer is unwrapped."""
    assert _client(fake_moonraker).server_info()["klippy_state"] == "ready"


def test_upload_stores_the_file_in_its_folder(fake_moonraker: FakeMoonraker, tmp_path: Path) -> None:
    """The file arrives whole, in the G-code root, in the folder asked for, not started."""
    gcode = tmp_path / "bracket.gcode"
    gcode.write_bytes(b"G28\n" * 300_000)

    result = _client(fake_moonraker).upload(gcode, "kits/arm")

    assert result.remote_path == "kits/arm/bracket.gcode"
    assert not result.print_started
    assert fake_moonraker.files["kits/arm/bracket.gcode"] == gcode.read_bytes()
    assert fake_moonraker.forms == [{"root": "gcodes", "print": "false", "path": "kits/arm"}]


def test_upload_can_start_the_print(fake_moonraker: FakeMoonraker, tmp_path: Path) -> None:
    """With start the printer is asked to print the file."""
    gcode = tmp_path / "cube.gcode"
    gcode.write_text("G28\n")

    result = _client(fake_moonraker).upload(gcode, start=True)

    assert result.print_started
    assert fake_moonraker.forms[0]["print"] == "true"
    assert "path" not in fake_moonraker.forms[0]


def test_api_key_is_sent_and_a_missing_one_is_explained(fake_moonraker: FakeMoonraker) -> None:
    """A printer that wants a key refuses without it, saying how to fix it."""
    fake_moonraker.api_key = "secret"

    with pytest.raises(MoonrakerError, match="api_key"):
        _client(fake_moonraker).server_info()
    assert _client(fake_moonraker, "secret").server_info()["klippy_state"] == "ready"


def test_refusals_use_moonrakers_message(fake_moonraker: FakeMoonraker, tmp_path: Path) -> None:
    """Moonraker's own reason is passed on."""
    fake_moonraker.fail_names = {"bad.gcode"}
    gcode = tmp_path / "bad.gcode"
    gcode.write_text("G28\n")

    with pytest.raises(MoonrakerError, match=r"HTTP 400\): Bad file bad.gcode"):
        _client(fake_moonraker).upload(gcode)


def test_unreachable_printer_is_explained() -> None:
    """A printer that does not answer is named in the error."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = MoonrakerClient(PrinterHost("k2", f"http://127.0.0.1:{port}"), timeout_seconds=2)

    with pytest.raises(MoonrakerError, match=r"Cannot reach k2 \(http://127.0.0.1"):
        client.server_info()


# --- planning and sending --------------------------------------------------


def _outcome(job: Path, *names: str, success: bool = True) -> SliceOutcome:
    return SliceOutcome(
        success=success,
        model=Path("/models") / f"{job.name}.stl",
        job_directory=job,
        gcode_files=tuple(job / name for name in names),
        message="",
        elapsed=1.0,
    )


def test_batch_keeps_its_folders_without_the_per_model_folder(tmp_path: Path) -> None:
    """batch/kits/arm/arm.gcode goes to batch/kits/arm.gcode on the printer; failures are left out."""
    batch = tmp_path / "out" / "models-20261122-073000"
    outcomes = [
        _outcome(batch / "kits" / "arm", "arm.gcode"),
        _outcome(batch / "cube", "cube.gcode", "cube_plate2.gcode"),
        _outcome(batch / "broken", success=False),
    ]

    uploads = plan_uploads(outcomes, tmp_path / "out")

    assert [upload.remote_path for upload in uploads] == [
        "models-20261122-073000/kits/arm.gcode",
        "models-20261122-073000/cube.gcode",
        "models-20261122-073000/cube_plate2.gcode",
    ]


def test_single_model_goes_to_the_top_folder(tmp_path: Path) -> None:
    """A single model's job folder sits directly in the output folder."""
    job = tmp_path / "out" / "cube-20261122-073000"

    uploads = plan_uploads([_outcome(job, "cube.gcode")], tmp_path / "out")

    assert [upload.remote_path for upload in uploads] == ["cube.gcode"]


def test_files_that_would_collide_keep_their_model_folder(tmp_path: Path) -> None:
    """cube.stl and cube.3mf both give cube.gcode, so those keep their own folders."""
    batch = tmp_path / "out" / "b"
    outcomes = [_outcome(batch / "cube", "cube.gcode"), _outcome(batch / "cube-2", "cube.gcode")]

    uploads = plan_uploads(outcomes, tmp_path / "out")

    assert [upload.remote_path for upload in uploads] == ["b/cube/cube.gcode", "b/cube-2/cube.gcode"]


def test_send_reports_each_file_and_carries_on_after_a_failure(
    fake_moonraker: FakeMoonraker, tmp_path: Path
) -> None:
    """One refused file does not stop the rest; start is ignored for several files."""
    fake_moonraker.fail_names = {"b.gcode"}
    uploads = []
    for name in ("a.gcode", "b.gcode", "c.gcode"):
        (tmp_path / name).write_text("G28\n")
        uploads.append(Upload(tmp_path / name, "batch"))
    seen: list[tuple[int, int, bool]] = []

    outcome = SendingService(_client(fake_moonraker), logger=Mock()).send(
        uploads, start=True, on_result=lambda n, total, result: seen.append((n, total, result.success))
    )

    assert seen == [(1, 3, True), (2, 3, False), (3, 3, True)]
    assert sorted(fake_moonraker.files) == ["batch/a.gcode", "batch/c.gcode"]
    assert {form["print"] for form in fake_moonraker.forms} == {"false"}
    assert "Bad file b.gcode" in outcome.failed[0].error
    assert len(outcome.sent) == 2


def test_single_file_can_be_started(fake_moonraker: FakeMoonraker, tmp_path: Path) -> None:
    """One file with start is printed; a busy printer keeps it without starting."""
    (tmp_path / "cube.gcode").write_text("G28\n")
    service = SendingService(_client(fake_moonraker), logger=Mock())

    assert service.send([Upload(tmp_path / "cube.gcode", "")], start=True).sent[0].print_started
    fake_moonraker.busy = True
    assert not service.send([Upload(tmp_path / "cube.gcode", "")], start=True).sent[0].print_started
    assert service.check().ready


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("192.168.1.50", "http://192.168.1.50:7125"),
        ("192.168.1.50:4408", "http://192.168.1.50:4408"),
        ("k2.local", "http://k2.local:7125"),
        ("http://192.168.1.50/", "http://192.168.1.50"),
        ("https://printer.example:8443", "https://printer.example:8443"),
    ],
)
def test_printer_address_can_be_given_directly(text: str, url: str) -> None:
    """An address needs no configuration; Moonraker's port 7125 is added when none is given."""
    host = host_from_address(text)

    assert host is not None
    assert host.url == url


def test_plain_names_and_bad_addresses() -> None:
    """A plain name is left for the configuration; a broken address is explained."""
    assert host_from_address("k2plus") is None
    with pytest.raises(PrinterHostError, match="not a printer address"):
        host_from_address("192.168.1.50:abc")
    with pytest.raises(PrinterHostError, match="not a printer address"):
        host_from_address("ftp://192.168.1.50")


# --- OctoPrint -------------------------------------------------------------


def _octoprint(fake: FakeOctoPrint, api_key: str | None = None) -> OctoPrintClient:
    key = fake.api_key if api_key is None else api_key
    return OctoPrintClient(PrinterHost("ender", fake.url, key, OCTOPRINT), timeout_seconds=5)


def test_octoprint_status(fake_octoprint: FakeOctoPrint) -> None:
    """OctoPrint's version and the printer's connection state are read."""
    status = _octoprint(fake_octoprint).status()
    assert (status.state, status.ready, status.software) == (
        "printer is Operational",
        True,
        "OctoPrint 1.10.3",
    )

    fake_octoprint.printer_state = "Offline"
    status = _octoprint(fake_octoprint).status()
    assert not status.ready
    assert status.note() == " (printer is Offline; it can still take files)"


def test_octoprint_wrong_api_key_is_explained(fake_octoprint: FakeOctoPrint) -> None:
    """A refused key points to OctoPrint's Application Keys."""
    with pytest.raises(PrinterError, match=r"HTTP 403.*Application Keys"):
        _octoprint(fake_octoprint, "wrong").status()


def test_octoprint_upload_creates_folders(fake_octoprint: FakeOctoPrint, tmp_path: Path) -> None:
    """Missing folders are created once, then files go into them; existing ones are fine."""
    for name in ("left.gcode", "right.gcode"):
        (tmp_path / name).write_text(f"; {name}\n")
    fake_octoprint.folders.add("kits")
    client = _octoprint(fake_octoprint)

    first = client.upload(tmp_path / "left.gcode", "kits/boat")
    second = client.upload(tmp_path / "right.gcode", "kits/boat")
    top = client.upload(tmp_path / "left.gcode")

    assert [first.remote_path, second.remote_path, top.remote_path] == [
        "kits/boat/left.gcode",
        "kits/boat/right.gcode",
        "left.gcode",
    ]
    assert fake_octoprint.folders == {"kits", "kits/boat"}
    assert fake_octoprint.files["kits/boat/right.gcode"] == b"; right.gcode\n"
    assert fake_octoprint.forms[0] == {"select": "false", "print": "false", "path": "kits/boat"}
    assert not first.print_started


def test_octoprint_start_and_busy_printer(fake_octoprint: FakeOctoPrint, tmp_path: Path) -> None:
    """A ready printer starts the file; one that is printing refuses to replace it."""
    (tmp_path / "cube.gcode").write_text("G28\n")
    service = SendingService(_octoprint(fake_octoprint), logger=Mock())

    started = service.send([Upload(tmp_path / "cube.gcode", "")], start=True)
    assert started.sent[0].print_started
    assert fake_octoprint.forms[-1] == {"select": "true", "print": "true"}

    again = service.send([Upload(tmp_path / "cube.gcode", "")], start=True)
    assert again.failed[0].error.endswith(
        "refused the request (HTTP 409): Trying to overwrite file that is currently being printed"
    )


def test_octoprint_not_ready_keeps_the_file_without_printing(
    fake_octoprint: FakeOctoPrint, tmp_path: Path
) -> None:
    """When the printer is not connected, the file is stored but not started."""
    (tmp_path / "cube.gcode").write_text("G28\n")
    fake_octoprint.printer_state = "Closed"

    result = _octoprint(fake_octoprint).upload(tmp_path / "cube.gcode", start=True)

    assert not result.print_started
    assert "cube.gcode" in fake_octoprint.files


def test_moonraker_address_is_not_octoprint(fake_moonraker: FakeMoonraker) -> None:
    """An OctoPrint printer set to a Moonraker address says it is not OctoPrint."""
    client = OctoPrintClient(PrinterHost("x", fake_moonraker.url, "k", OCTOPRINT), timeout_seconds=5)
    with pytest.raises(PrinterError, match="no OctoPrint at that address"):
        client.status()


def test_loaded_filaments_are_read_from_moonraker(fake_moonraker: FakeMoonraker) -> None:
    """The CFS state comes from /printer/objects/query; a printer without one reports none."""
    from test_filaments import K2_STATUS

    assert _client(fake_moonraker).loaded_filaments() == []
    fake_moonraker.objects = K2_STATUS
    assert [item.slot for item in _client(fake_moonraker).loaded_filaments()] == ["1B", "1C", "external"]
    assert OctoPrintClient(PrinterHost("x", "http://x", "k", OCTOPRINT)).loaded_filaments() == []


def test_flat_gcode_is_sent_into_the_batch_folder(tmp_path: Path) -> None:
    """G-code moved up into the batch folder (--flat) goes into that one folder on the printer."""
    batch = tmp_path / "out" / "kits-20261123-073000"
    outcome = SliceOutcome(
        success=True, model=tmp_path / "in" / "b" / "arm.stl", job_directory=batch / "b" / "arm",
        gcode_files=(batch / "b-arm.gcode",), message="", elapsed=1.0,
    )

    [upload] = plan_uploads([outcome], tmp_path / "out")

    assert upload.remote_path == "kits-20261123-073000/b-arm.gcode"
