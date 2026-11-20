"""Describe targets and profiles: reusable choices for a slicing run.

A *target* is one slicer with its printer, filament and process presets. A run
slices its input for one or more targets. A *profile* names a set of targets
together with the shared input and output, so a run can be repeated. Any
choice may be left unset; unset choices are asked for, or given on the command
line, as usual. This module only describes them; it does not store them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

LAST_RUN = "last"
"""Name of the profile that remembers the most recent run."""

TARGET_FIELDS = ("slicer", "printer", "filament", "process")
"""The choices a target holds, in display order."""

RUN_FIELDS = ("input", "output")
"""The choices shared by every target in a run."""

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class Target:
    """One slicer and its presets; ``None`` means "not chosen yet"."""

    slicer: str | None = None
    """Configuration key of the slicer, for example ``creality_print``."""

    printer: str | None = None
    filament: str | None = None
    process: str | None = None

    def summary(self) -> str:
        """Return the target's choices as one line."""
        parts = [getattr(self, key) for key in TARGET_FIELDS if getattr(self, key)]
        return ", ".join(parts) if parts else "no choices saved"

    def is_empty(self) -> bool:
        """Return whether no choice is set."""
        return not any(getattr(self, key) for key in TARGET_FIELDS)


@dataclass(frozen=True, slots=True)
class Profile:
    """A named run: one or more targets and the input and output they share."""

    name: str
    targets: tuple[Target, ...] = field(default=(Target(),))
    input: Path | None = None
    output: Path | None = None

    @classmethod
    def single(
        cls,
        name: str,
        *,
        slicer: str | None = None,
        printer: str | None = None,
        filament: str | None = None,
        process: str | None = None,
        input: Path | None = None,  # noqa: A002 - matches the option name
        output: Path | None = None,
    ) -> "Profile":
        """Return a profile with one target."""
        target = Target(slicer=slicer, printer=printer, filament=filament, process=process)
        return cls(name=name, targets=(target,), input=input, output=output)

    @property
    def is_multi(self) -> bool:
        """Return whether the profile slices for more than one target."""
        return len(self.targets) > 1

    def summary(self) -> str:
        """Return a one-line description of the choices this profile sets."""
        if self.is_multi:
            names = [target.printer or target.slicer or "?" for target in self.targets]
            labels = [
                f"{name} ({target.slicer})" if names.count(name) > 1 and target.slicer else name
                for name, target in zip(names, self.targets, strict=True)
            ]
            parts = [f"{len(self.targets)} printers: " + "; ".join(labels)]
        else:
            parts = [] if self.targets[0].is_empty() else [self.targets[0].summary()]
        if self.input is not None:
            parts.append(f"input {self.input}")
        if self.output is not None:
            parts.append(f"output {self.output}")
        return ", ".join(parts) if parts else "no choices saved"


def combine(name: str, profiles: Iterable[Profile]) -> Profile:
    """Return one profile holding every target of ``profiles``.

    Input and output come from the first profile that sets them.
    """
    chosen = list(profiles)
    targets = tuple(
        target for profile in chosen for target in profile.targets if not target.is_empty()
    )
    return Profile(
        name=name,
        targets=targets or (Target(),),
        input=next((profile.input for profile in chosen if profile.input), None),
        output=next((profile.output for profile in chosen if profile.output), None),
    )


def is_valid_name(name: str) -> bool:
    """Return whether ``name`` can be used as a profile name.

    Names start with a letter or digit and may contain letters, digits, spaces,
    dots, dashes and underscores, up to 64 characters.
    """
    return bool(_NAME_PATTERN.match(name))
