"""Tests for ``batchslicer printers``: listing the configured printers for people and programs."""

import json
from pathlib import Path

import pytest
import yaml

from batchslicer.app import main
from batchslicer.cli.arguments import parse_arguments
from batchslicer.cli.printers import PrintersOptions, printers_json, run_printers
from batchslicer.domain.printers import PrinterHost, PrinterHostError, printer_hosts

PRINTERS = {
    "k2plus": {"url": "http://192.168.1.50:7125"},
    "voron": {"url": "http://voron.local:7125", "api_key": "secret-in-file"},
    "octo": {"url": "http://octo.local", "type": "octoprint", "api_key_env": "OCTO_KEY"},
}


def _config(tmp_path: Path, printers: object = PRINTERS) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"printers": printers}, sort_keys=False), encoding="utf-8")
    return path


def test_json_lists_every_printer_without_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keys in the file are only flagged; keys in variables are only named (even when set)."""
    monkeypatch.setenv("OCTO_KEY", "secret-in-variable")

    assert run_printers(PrintersOptions(config=_config(tmp_path), json=True)) == 0

    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["format"] == 1
    assert data["printers"] == [
        {"name": "k2plus", "type": "moonraker", "url": "http://192.168.1.50:7125"},
        {"name": "voron", "type": "moonraker", "url": "http://voron.local:7125", "has_api_key": True},
        {"name": "octo", "type": "octoprint", "url": "http://octo.local", "api_key_env": "OCTO_KEY"},
    ]
    assert "secret" not in output


def test_with_keys_adds_only_the_keys_written_in_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--with-keys includes file keys; a variable's value is still never printed."""
    monkeypatch.setenv("OCTO_KEY", "secret-in-variable")

    run_printers(PrintersOptions(config=_config(tmp_path), json=True, with_keys=True))

    output = capsys.readouterr().out
    voron = json.loads(output)["printers"][1]
    assert voron["api_key"] == "secret-in-file"
    assert "secret-in-variable" not in output


def test_printers_whose_key_variable_is_not_set_are_still_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing does not need the API-key variables (the reading program has its own)."""
    monkeypatch.delenv("OCTO_KEY", raising=False)

    assert run_printers(PrintersOptions(config=_config(tmp_path), json=True)) == 0
    assert json.loads(capsys.readouterr().out)["printers"][2]["api_key_env"] == "OCTO_KEY"


def test_using_printers_still_needs_the_key_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check stays on everywhere else: --send fails clearly without the variable."""
    monkeypatch.delenv("OCTO_KEY", raising=False)

    with pytest.raises(PrinterHostError, match="OCTO_KEY"):
        printer_hosts(PRINTERS)


def test_text_lists_one_line_per_printer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Without --json, a line each, saying where any API key comes from."""
    assert run_printers(PrintersOptions(config=_config(tmp_path))) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "k2plus (http://192.168.1.50:7125)",
        "voron (http://voron.local:7125), API key in the file",
        "octo (OctoPrint, http://octo.local), API key from $OCTO_KEY",
    ]


def test_no_printers_and_broken_configurations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No printers says how to add them; a mistake gives exit status 1 (and JSON with the error)."""
    assert run_printers(PrintersOptions(config=_config(tmp_path, printers={}))) == 0
    assert "No printers are configured" in capsys.readouterr().out

    broken = _config(tmp_path, printers={"bad name!": {"url": "x"}})
    assert run_printers(PrintersOptions(config=broken, json=True)) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["printers"] == [] and "printer names" in data["error"]


def test_the_command_is_parsed_and_run_from_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``batchslicer printers --json`` runs the command; --with-keys needs --json."""
    assert parse_arguments(["printers", "--json"]) == PrintersOptions(json=True)
    with pytest.raises(SystemExit):
        parse_arguments(["printers", "--with-keys"])

    assert main(["printers", "--config", str(_config(tmp_path)), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["printers"][0]["name"] == "k2plus"


def test_printers_json_shape() -> None:
    """A printer without a key has only its name, type and address."""
    data = json.loads(printers_json([PrinterHost(name="k2", url="http://k2:7125")]))

    assert data == {"format": 1, "printers": [{"name": "k2", "type": "moonraker", "url": "http://k2:7125"}]}
