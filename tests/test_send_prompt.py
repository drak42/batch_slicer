"""Tests for asking whether to send the G-code to a printer."""

from collections.abc import Callable, Iterator

import pytest

from batchslicer.cli.send_prompt import prompt_for_printer
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.printers import PrinterHost

K2 = PrinterHost("k2plus", "http://192.168.1.242:7125")
VORON = PrinterHost("voron", "http://192.168.1.50:7125")


def _answers(*values: str) -> Callable[[str], str]:
    remaining: Iterator[str] = iter(values)
    return lambda _prompt: next(remaining)


def _ask(*answers: str, printers: list[PrinterHost] | None = None, last: PrinterHost | None = None) -> tuple[PrinterHost | None, list[str]]:
    lines: list[str] = []
    chosen = prompt_for_printer(
        [K2, VORON] if printers is None else printers, last=last, read_line=_answers(*answers), write=lines.append
    )
    return chosen, lines


def test_enter_means_dont_send_unless_the_last_run_sent() -> None:
    """Enter keeps what the last run did."""
    assert _ask("")[0] is None
    chosen, lines = _ask("", last=VORON)
    assert chosen == VORON
    assert "  2) voron (http://192.168.1.50:7125)  (last time)" in lines


def test_numbers_pick_a_printer_or_not_sending() -> None:
    """0 is don't send; other numbers are the listed printers."""
    assert _ask("1")[0] == K2
    assert _ask("0", last=K2)[0] is None
    chosen, lines = _ask("7", "2")
    assert chosen == VORON
    assert any("number from 0 to 2" in line for line in lines)


def test_an_address_or_a_name_can_be_typed() -> None:
    """A typed address is used directly (port 7125 by default); a name picks that printer."""
    typed, _ = _ask("192.168.1.99")
    assert typed == PrinterHost("192.168.1.99", "http://192.168.1.99:7125")
    assert _ask("VORON")[0] == VORON
    chosen, lines = _ask("192.168.1.99:abc", "1")
    assert chosen == K2
    assert any("not a printer address" in line for line in lines)


def test_last_printer_not_in_the_configuration_is_offered() -> None:
    """An address the last run sent to is listed after the configured printers."""
    last = PrinterHost("192.168.1.242", "http://192.168.1.242:7125")
    chosen, lines = _ask("", printers=[VORON], last=last)
    assert chosen == last
    assert "  2) 192.168.1.242 (http://192.168.1.242:7125)  (last time)" in lines


def test_ended_input_cancels() -> None:
    """Ctrl+D or Ctrl+C stops with a clear error."""
    def ended(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(SlicerSelectionError, match="Cancelled"):
        prompt_for_printer([K2], read_line=ended, write=lambda _: None)
