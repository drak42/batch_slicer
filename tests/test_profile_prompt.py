"""Tests for offering saved profiles at the start of a run."""

from collections.abc import Callable, Iterator

import pytest

from batchslicer.cli.profile_prompt import prompt_for_profile
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.profiles import Profile


def _answers(*values: str) -> Callable[[str], str]:
    """Return a read_line replacement that yields ``values`` in order."""
    iterator: Iterator[str] = iter(values)

    def read_line(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read_line


PROFILES = {
    "zebra": Profile(name="zebra", slicer="orca"),
    "last": Profile(name="last", slicer="creality_print"),
    "alpha": Profile(name="alpha", slicer="bambu_studio"),
}


def test_last_run_is_listed_first_then_by_name() -> None:
    """The last run comes first; the rest are alphabetical."""
    lines: list[str] = []

    prompt_for_profile(PROFILES, read_line=_answers(""), write=lines.append)

    assert lines == [
        "Start from a saved profile?",
        "  1) last run: creality_print",
        "  2) alpha: bambu_studio",
        "  3) zebra: orca",
    ]


def test_enter_means_choose_everything() -> None:
    """Pressing Enter skips profiles."""
    assert prompt_for_profile(PROFILES, read_line=_answers(""), write=lambda _: None) is None


def test_number_picks_a_profile_after_bad_answers() -> None:
    """Invalid answers are explained and the question repeats."""
    lines: list[str] = []

    chosen = prompt_for_profile(PROFILES, read_line=_answers("9", "x", "3"), write=lines.append)

    assert chosen is PROFILES["zebra"]
    assert lines.count("Please enter a number from 1 to 3, or press Enter.") == 2


def test_end_of_input_stops() -> None:
    """Closing input stops instead of looping."""
    with pytest.raises(SlicerSelectionError, match="No profile selected"):
        prompt_for_profile(PROFILES, read_line=_answers(), write=lambda _: None)
