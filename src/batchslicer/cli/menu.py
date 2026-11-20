"""Show a numbered, searchable list and return the item the user picks.

Entering a number picks that item. Entering text shows only items whose label
contains it; an empty answer shows the full list again. A caller can also
accept typed text directly (for example a file path). This module only handles
the conversation; it knows nothing about slicers, presets or files.
"""

from collections.abc import Callable, Sequence
from typing import TypeVar

from batchslicer.cli.slicer_prompt import SlicerSelectionError


ItemT = TypeVar("ItemT")


def choose(
    items: Sequence[ItemT],
    *,
    noun: str,
    plural: str,
    label: Callable[[ItemT], str],
    read_line: Callable[[str], str],
    write: Callable[[str], None],
    prompt: str,
    accept_text: Callable[[str], ItemT | None] | None = None,
    heading: str | None = None,
) -> ItemT:
    """Return the item the user picks from ``items``.

    ``noun`` names one item in headings ("Select a <noun>") and ``plural``
    names several in messages. ``accept_text`` is tried on any answer that is
    not a number; if it returns an item, that item is chosen, which lets the
    user type something not in the list. :class:`SlicerSelectionError` is
    raised when there is nothing to choose or input ends or is interrupted.
    ``heading`` replaces the default "Select a <noun>" heading.
    """
    if not items and accept_text is None:
        raise SlicerSelectionError(f"No {plural} were found.")

    title = heading or f"Select a {noun}"
    shown = list(items)
    if shown:
        _show(title, shown, len(items), label, write)
    while True:
        try:
            answer = read_line(prompt).strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError(f"No {noun} selected.") from error

        if answer.isdigit() and shown:
            number = int(answer)
            if 1 <= number <= len(shown):
                return shown[number - 1]
            write(f"Please enter a number from 1 to {len(shown)}.")
            continue

        if accept_text is not None and answer:
            accepted = accept_text(answer)
            if accepted is not None:
                return accepted

        if not items:
            continue

        matches = [item for item in items if answer.casefold() in label(item).casefold()]
        if not matches:
            write(f"No {plural} match '{answer}'.")
            continue
        shown = matches
        _show(title, shown, len(items), label, write)


def confirm(
    question: str,
    *,
    read_line: Callable[[str], str],
    write: Callable[[str], None],
    default: bool = True,
) -> bool:
    """Ask a yes/no question; an empty answer means ``default``.

    Raises :class:`SlicerSelectionError` when input ends or is interrupted.
    """
    choices = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = read_line(f"{question} {choices} ").strip().casefold()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError("Cancelled.") from error
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        write("Please answer y or n.")


def _show(
    title: str,
    items: Sequence[ItemT],
    total: int,
    label: Callable[[ItemT], str],
    write: Callable[[str], None],
) -> None:
    """Print a numbered list with a heading that says when it is filtered."""
    heading = title
    if len(items) < total:
        heading += f" ({len(items)} of {total} shown; press Enter for all)"
    write(heading if heading.endswith(("?", ":")) else f"{heading}:")
    for number, item in enumerate(items, start=1):
        write(f"  {number}) {label(item)}")
