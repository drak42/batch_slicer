"""Ask the user which slicer BatchSlicer should use for this run.

This module owns the interactive slicer menu. It lists every supported slicer,
marks the ones without configuration as unavailable, and repeats the question
until a configured slicer is chosen. It does not read configuration, verify
slicer paths, or run slicers.
"""

from collections.abc import Callable, Sequence

from batchslicer.backends.slicers import SlicerDefinition


class SlicerSelectionError(Exception):
    """Raised when a slicer or preset cannot be chosen, or the user stops the prompt."""


def prompt_for_slicer(
    slicers: Sequence[SlicerDefinition],
    configured: Sequence[SlicerDefinition],
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> SlicerDefinition:
    """Show the slicer menu and return the configured slicer the user picks.

    Raises :class:`SlicerSelectionError` when no slicer is configured, or when
    input ends or is interrupted before a choice is made.
    """
    if not configured:
        sections = ", ".join(f"{slicer.key}:" for slicer in slicers)
        raise SlicerSelectionError(
            "No slicer is configured. Set executable and datadir for at least one "
            f"of {sections} in your BatchSlicer configuration file."
        )

    write("Select a slicer:")
    for number, slicer in enumerate(slicers, start=1):
        note = "" if slicer in configured else "  (not configured)"
        write(f"  {number}) {slicer.display_name}{note}")

    while True:
        try:
            answer = read_line(f"Enter 1-{len(slicers)}: ").strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")  # End the unanswered prompt line before the error is shown.
            raise SlicerSelectionError("No slicer selected.") from error

        if answer.isdigit() and 1 <= int(answer) <= len(slicers):
            chosen = slicers[int(answer) - 1]
            if chosen in configured:
                return chosen
            write(
                f"{chosen.display_name} is not configured. Set {chosen.key}.executable "
                f"and {chosen.key}.datadir in your BatchSlicer configuration file, or choose another slicer."
            )
        else:
            write(f"Please enter a number from 1 to {len(slicers)}.")
