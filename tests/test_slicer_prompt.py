"""Tests for the interactive slicer selection prompt."""

from collections.abc import Callable, Iterator

import pytest

from batchslicer.backends.slicers import BAMBU_STUDIO, CREALITY_PRINT, ORCASLICER, SLICERS
from batchslicer.cli.slicer_prompt import SlicerSelectionError, prompt_for_slicer


def _answers(*values: str) -> Callable[[str], str]:
    """Return a read_line replacement that yields ``values`` in order."""
    iterator: Iterator[str] = iter(values)

    def read_line(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read_line


def test_lists_every_slicer_and_marks_unconfigured_ones() -> None:
    """All slicers are shown; those without configuration are marked."""
    lines: list[str] = []

    prompt_for_slicer(SLICERS, [ORCASLICER], read_line=_answers("1"), write=lines.append)

    assert lines == [
        "Select a slicer:",
        "  1) OrcaSlicer",
        "  2) Creality Print  (not configured)",
        "  3) Bambu Studio  (not configured)",
    ]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("1", ORCASLICER), ("2", CREALITY_PRINT), (" 3 ", BAMBU_STUDIO)],
)
def test_returns_the_chosen_slicer(answer: str, expected: object) -> None:
    """Each menu number selects the matching slicer."""
    chosen = prompt_for_slicer(SLICERS, SLICERS, read_line=_answers(answer), write=lambda _: None)

    assert chosen is expected


def test_repeats_until_a_valid_configured_choice() -> None:
    """Invalid input and unconfigured slicers are refused and the question repeats."""
    lines: list[str] = []

    chosen = prompt_for_slicer(
        SLICERS,
        [BAMBU_STUDIO],
        read_line=_answers("", "abc", "9", "1", "3"),
        write=lines.append,
    )

    assert chosen is BAMBU_STUDIO
    assert lines.count("Please enter a number from 1 to 3.") == 3
    assert any("OrcaSlicer is not configured" in line for line in lines)


def test_end_of_input_stops_selection() -> None:
    """Closing input (Ctrl+D or no terminal) stops instead of looping forever."""
    with pytest.raises(SlicerSelectionError, match="No slicer selected"):
        prompt_for_slicer(SLICERS, SLICERS, read_line=_answers(), write=lambda _: None)


def test_ctrl_c_stops_selection() -> None:
    """Ctrl+C at the prompt stops selection cleanly."""

    def interrupted(prompt: str) -> str:
        raise KeyboardInterrupt

    with pytest.raises(SlicerSelectionError):
        prompt_for_slicer(SLICERS, SLICERS, read_line=interrupted, write=lambda _: None)


def test_no_configured_slicer_explains_what_to_set() -> None:
    """With nothing configured there is nothing to choose, and the error says why."""
    with pytest.raises(SlicerSelectionError, match="No slicer is configured"):
        prompt_for_slicer(SLICERS, [], read_line=_answers("1"), write=lambda _: None)
