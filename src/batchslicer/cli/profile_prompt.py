"""Offer saved profiles at the start of an interactive run.

Lists the saved profiles with a summary of each; picking one starts the run
from its choices, and pressing Enter skips them so every choice is asked for as
usual. This module only handles the conversation; it does not store profiles.
"""

from collections.abc import Callable, Mapping

from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.profiles import LAST_RUN, Profile


def prompt_for_profile(
    profiles: Mapping[str, Profile],
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> Profile | None:
    """Return the profile the user picks, or None to choose everything instead.

    The last run is listed first. Raises :class:`SlicerSelectionError` if input
    ends or is interrupted.
    """
    ordered = sorted(
        profiles.values(),
        key=lambda profile: (profile.name != LAST_RUN, profile.name.casefold()),
    )
    write("Start from a saved profile?")
    for number, profile in enumerate(ordered, start=1):
        name = "last run" if profile.name == LAST_RUN else profile.name
        write(f"  {number}) {name}: {profile.summary()}")
    while True:
        try:
            answer = read_line(
                f"Profile number 1-{len(ordered)}, or Enter to choose everything yourself: "
            ).strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError("No profile selected.") from error
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(ordered):
            return ordered[int(answer) - 1]
        write(f"Please enter a number from 1 to {len(ordered)}, or press Enter.")
