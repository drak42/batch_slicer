"""Tests for the shared menu questions."""

from collections.abc import Callable, Iterator

import pytest

from batchslicer.cli.menu import ask_number
from batchslicer.cli.slicer_prompt import SlicerSelectionError


def _answers(*values: str) -> Callable[[str], str]:
    remaining: Iterator[str] = iter(values)
    return lambda _prompt: next(remaining)


def test_ask_number_takes_the_default_or_a_number_in_range() -> None:
    """Enter gives the default; numbers outside the range are asked again."""
    lines: list[str] = []

    def ask(*answers: str) -> int:
        return ask_number("How many?", default=1, minimum=1, maximum=10,
                          read_line=_answers(*answers), write=lines.append)

    assert ask("") == 1
    assert ask("7") == 7
    assert ask("0", "x", "11", "3") == 3
    assert lines.count("Please enter a number from 1 to 10.") == 3


def test_ask_number_can_be_cancelled() -> None:
    """Ctrl+D stops with a clear error."""
    def ended(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(SlicerSelectionError, match="Cancelled"):
        ask_number("How many?", default=1, minimum=1, maximum=10, read_line=ended, write=lambda _: None)
