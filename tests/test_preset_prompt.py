"""Tests for the printer, filament and process selection prompt."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from batchslicer.cli.preset_prompt import (
    choose_preset,
    find_preset,
    prompt_for_presets,
    select_presets,
)
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.presets import Preset, PresetKind


def _answers(*values: str) -> Callable[[str], str]:
    """Return a read_line replacement that yields ``values`` in order."""
    iterator: Iterator[str] = iter(values)

    def read_line(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read_line


def _preset(name: str, kind: PresetKind = PresetKind.FILAMENT, *, mine: bool = False) -> Preset:
    """Create a preset for tests."""
    return Preset(name=name, kind=kind, path=Path(f"{name}.json"), is_user=mine)


FILAMENTS = [
    _preset("My PETG", mine=True),
    _preset("Generic PLA"),
    _preset("Generic PETG"),
    _preset("Hyper PLA"),
]


def test_lists_presets_and_marks_the_users_own() -> None:
    """The list is numbered and the user's presets are marked."""
    lines: list[str] = []

    choose_preset(PresetKind.FILAMENT, FILAMENTS, _answers("2"), lines.append)

    assert lines == [
        "Select a filament:",
        "  1) My PETG  (mine)",
        "  2) Generic PLA",
        "  3) Generic PETG",
        "  4) Hyper PLA",
    ]


def test_number_selects_preset() -> None:
    """A number picks that preset."""
    chosen = choose_preset(PresetKind.FILAMENT, FILAMENTS, _answers("4"), lambda _: None)

    assert chosen.name == "Hyper PLA"


def test_text_narrows_the_list_and_numbers_follow_it() -> None:
    """Typing text shows matching presets, renumbered; numbers then refer to that list."""
    lines: list[str] = []

    chosen = choose_preset(PresetKind.FILAMENT, FILAMENTS, _answers("petg", "2"), lines.append)

    assert chosen.name == "Generic PETG"
    assert "Select a filament (2 of 4 shown; press Enter for all):" in lines
    assert "  2) Generic PETG" in lines


def test_empty_answer_shows_everything_again() -> None:
    """Pressing Enter after a search returns to the full list."""
    chosen = choose_preset(
        PresetKind.FILAMENT, FILAMENTS, _answers("petg", "", "4"), lambda _: None
    )

    assert chosen.name == "Hyper PLA"


def test_invalid_answers_are_explained() -> None:
    """Out-of-range numbers and searches with no matches ask again."""
    lines: list[str] = []

    choose_preset(PresetKind.FILAMENT, FILAMENTS, _answers("9", "nylon", "1"), lines.append)

    assert "Please enter a number from 1 to 4." in lines
    assert "No filament presets match 'nylon'." in lines


def test_end_of_input_stops_selection() -> None:
    """Closing input stops instead of looping."""
    with pytest.raises(SlicerSelectionError, match="No filament selected"):
        choose_preset(PresetKind.FILAMENT, FILAMENTS, _answers(), lambda _: None)


def test_empty_list_is_an_error() -> None:
    """With nothing compatible there is nothing to choose."""
    with pytest.raises(SlicerSelectionError, match="No compatible process presets"):
        choose_preset(PresetKind.PROCESS, [], _answers("1"), lambda _: None)


class _Source:
    """A preset source that records which printer it was asked about."""

    def __init__(self) -> None:
        self.asked_for: list[str] = []

    def printers(self) -> list[Preset]:
        return [_preset("Ender", PresetKind.PRINTER), _preset("K2", PresetKind.PRINTER)]

    def filaments_for(self, printer: Preset) -> list[Preset]:
        self.asked_for.append(printer.name)
        return [_preset(f"PLA @{printer.name}")]

    def processes_for(self, printer: Preset) -> list[Preset]:
        self.asked_for.append(printer.name)
        return [_preset(f"Fine @{printer.name}", PresetKind.PROCESS)]


def test_printer_is_chosen_first_and_filters_the_rest() -> None:
    """Filament and process lists come from the chosen printer, asked in that order."""
    source = _Source()

    selection = prompt_for_presets(source, read_line=_answers("2", "1", "1"), write=lambda _: None)

    assert source.asked_for == ["K2", "K2"]
    assert selection.printer.name == "K2"
    assert selection.filament.name == "PLA @K2"
    assert selection.process.name == "Fine @K2"


def test_named_presets_are_used_without_asking() -> None:
    """Names given on the command line are matched ignoring case; nothing is asked."""
    source = _Source()

    selection = select_presets(
        source,
        printer="k2",
        filament="PLA @K2",
        process="fine @k2",
        prompt=False,
        read_line=_answers(),
        write=lambda _: None,
    )

    assert (selection.printer.name, selection.filament.name, selection.process.name) == (
        "K2",
        "PLA @K2",
        "Fine @K2",
    )


def test_only_missing_presets_are_asked_for() -> None:
    """A named printer is used and the filament and process are still asked for."""
    selection = select_presets(
        _Source(), printer="Ender", read_line=_answers("1", "1"), write=lambda _: None
    )

    assert selection.printer.name == "Ender"
    assert selection.filament.name == "PLA @Ender"


def test_missing_preset_without_prompts_names_the_option() -> None:
    """With prompting off, a missing preset names the option to add."""
    with pytest.raises(SlicerSelectionError, match="--filament is required"):
        select_presets(_Source(), printer="K2", prompt=False, read_line=_answers(), write=print)


def test_unknown_name_suggests_close_matches() -> None:
    """A mistyped name is refused with suggestions and a pointer to --list-presets."""
    with pytest.raises(SlicerSelectionError) as raised:
        find_preset(PresetKind.FILAMENT, FILAMENTS, "Generic PTEG")

    message = str(raised.value)
    assert "No filament preset named 'Generic PTEG'" in message
    assert "'Generic PETG'" in message
    assert "--list-presets" in message


def test_filament_for_another_printer_is_refused() -> None:
    """A filament that exists but does not fit the chosen printer is not accepted."""
    with pytest.raises(SlicerSelectionError, match="compatible with K2"):
        select_presets(
            _Source(), printer="K2", filament="PLA @Ender", process="Fine @K2", prompt=False
        )
