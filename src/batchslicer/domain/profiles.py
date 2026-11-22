"""Describe targets and profiles: reusable choices for a slicing run.

A *target* is one slicer with its printer, filament and process presets, and
optionally the networked printer its G-code is sent to. A run
slices its input for one or more targets. A *profile* names a set of targets
together with the shared input and output, so a run can be repeated. Any
choice may be left unset; unset choices are asked for, or given on the command
line, as usual. This module only describes them; it does not store them.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from batchslicer.domain.options import OrientMode

LAST_RUN = "last"
"""Name of the profile that remembers the most recent run."""

TARGET_FIELDS = ("slicer", "printer", "filament", "process", "send")
"""The choices a target holds, in display order."""

RUN_FIELDS = ("input", "output")
"""The paths shared by every target in a run."""

SETTING_FIELDS = (
    "orient", "allow_newer_files", "jobs", "exclude", "thumbnails", "plates", "copies",
    "loaded_filaments",
)
"""How the run slices (see :mod:`batchslicer.domain.options`), shared by every target."""

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class Target:
    """One slicer and its presets; ``None`` means "not chosen yet"."""

    slicer: str | None = None
    """Configuration key of the slicer, for example ``creality_print``."""

    printer: str | None = None
    filament: str | None = None
    process: str | None = None
    send: str | None = None
    """Name of the configured printer the G-code is sent to (--send)."""

    more_filaments: tuple[str, ...] = ()
    """Filaments for slots 2, 3... of a multi-material printer (stored with ``filament`` as a list)."""

    @property
    def filaments(self) -> tuple[str, ...]:
        """Return every chosen filament, slot 1 first; empty when none is chosen."""
        return (self.filament, *self.more_filaments) if self.filament else ()

    def summary(self) -> str:
        """Return the target's choices as one line."""
        parts = [
            " + ".join(self.filaments) if key == "filament" else getattr(self, key)
            for key in TARGET_FIELDS[:-1]
            if getattr(self, key)
        ]
        if self.send:
            parts.append(f"send to {self.send}")
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
    orient: OrientMode | None = None
    allow_newer_files: bool | None = None
    jobs: int | None = None
    exclude: tuple[str, ...] | None = None
    thumbnails: bool | None = None
    plates: bool | None = None
    copies: int | None = None
    loaded_filaments: bool | None = None

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
        if self.orient is not None:
            parts.append(f"orient {self.orient}")
        if self.allow_newer_files is not None:
            parts.append("newer files allowed" if self.allow_newer_files else "newer files refused")
        if self.jobs is not None:
            parts.append(f"{self.jobs} job{'s' if self.jobs != 1 else ''}")
        if self.exclude:
            parts.append("excluding " + ", ".join(self.exclude))
        if self.copies is not None and self.copies > 1:
            parts.append(f"{self.copies} copies")
        if self.plates is not None:
            parts.append("models together on plates" if self.plates else "one model per plate")
        if self.thumbnails is not None:
            parts.append("preview pictures" if self.thumbnails else "no preview pictures")
        if self.loaded_filaments:
            parts.append("colours matched to the loaded filaments")
        return ", ".join(parts) if parts else "no choices saved"


def combine(name: str, profiles: Iterable[Profile]) -> Profile:
    """Return one profile holding every target of ``profiles``.

    Input, output and the slicing settings come from the first profile that
    sets them.
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
        orient=next((p.orient for p in chosen if p.orient is not None), None),
        allow_newer_files=next(
            (p.allow_newer_files for p in chosen if p.allow_newer_files is not None), None
        ),
        jobs=next((p.jobs for p in chosen if p.jobs is not None), None),
        exclude=next((p.exclude for p in chosen if p.exclude is not None), None),
        thumbnails=next((p.thumbnails for p in chosen if p.thumbnails is not None), None),
        plates=next((p.plates for p in chosen if p.plates is not None), None),
        copies=next((p.copies for p in chosen if p.copies is not None), None),
        loaded_filaments=next(
            (p.loaded_filaments for p in chosen if p.loaded_filaments is not None), None
        ),
    )


def is_valid_name(name: str) -> bool:
    """Return whether ``name`` can be used as a profile name.

    Names start with a letter or digit and may contain letters, digits, spaces,
    dots, dashes and underscores, up to 64 characters.
    """
    return bool(_NAME_PATTERN.match(name))
