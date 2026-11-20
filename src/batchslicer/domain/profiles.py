"""Describe a profile: a named, reusable set of choices for a slicing run.

A profile can hold any of the choices a run needs (slicer, presets, input and
output). Choices it leaves out are asked for, or given on the command line,
as usual. This module only describes profiles; it does not store them.
"""

import re
from dataclasses import dataclass, fields
from pathlib import Path

LAST_RUN = "last"
"""Name of the profile that remembers the most recent run."""

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class Profile:
    """A named set of run choices; ``None`` means "not set by this profile"."""

    name: str
    slicer: str | None = None
    """Configuration key of the slicer, for example ``creality_print``."""

    printer: str | None = None
    filament: str | None = None
    process: str | None = None
    input: Path | None = None
    output: Path | None = None

    def summary(self) -> str:
        """Return a one-line description of the choices this profile sets."""
        parts = [
            value
            for value in (self.slicer, self.printer, self.filament, self.process)
            if value
        ]
        if self.input is not None:
            parts.append(f"input {self.input}")
        if self.output is not None:
            parts.append(f"output {self.output}")
        return ", ".join(parts) if parts else "no choices saved"


CHOICE_FIELDS = tuple(field.name for field in fields(Profile) if field.name != "name")
"""The choices a profile can hold, in display order."""


def is_valid_name(name: str) -> bool:
    """Return whether ``name`` can be used as a profile name.

    Names start with a letter or digit and may contain letters, digits, spaces,
    dots, dashes and underscores, up to 64 characters.
    """
    return bool(_NAME_PATTERN.match(name))
