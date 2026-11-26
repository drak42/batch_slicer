"""Describe how models are sliced, beyond the presets: orientation, file versions, pictures.

These options change what is asked of the slicer for every model in a run.
They are plain values shared by the command line, profiles and the slicing
service; this module does not run slicers.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from batchslicer.domain.patterns import normalise, path_matches

OrientMode: TypeAlias = Literal["off", "retry", "always"]

ORIENT_MODES: tuple[OrientMode, ...] = ("off", "retry", "always")
"""When the slicer's auto-orient is used.

``off``: models are sliced as they were saved. ``retry``: a model that fails is
sliced once more with auto-orient. ``always``: every model is auto-oriented,
which may rotate parts that were saved in the orientation meant for printing.
"""

MAX_JOBS = 64
"""The most models that may be sliced at the same time."""

MAX_COPIES = 500
"""The most copies of a single model that may be asked for."""

COPYABLE_SUFFIXES = frozenset({".stl", ".obj", ".step", ".stp"})
"""Model files that can be copied (3MF projects keep their own plates)."""

MAX_SLOT = 16
"""The highest filament slot number (four CFS or AMS units of four)."""

_LOADED_SLOT = re.compile(r"^(?:[1-4][A-Da-d]|external)$", re.IGNORECASE)

SlotRule: TypeAlias = tuple[str, str]
"""``(pattern, slot)`` from ``--slot PATTERN=SLOT``."""


def slot_value(text: str) -> str:
    """Return a ``--slot`` slot: a number from 1 to :data:`MAX_SLOT`, a CFS slot such as
    ``1B``, or ``external``. Raises ``ValueError`` for anything else."""
    value = text.strip()
    if value.isdigit() and 1 <= int(value) <= MAX_SLOT:
        return str(int(value))
    if _LOADED_SLOT.match(value):
        return value.casefold() if value.casefold() == "external" else value.upper()
    raise ValueError(
        f"'{text}' is not a filament slot: use a number from 1 to {MAX_SLOT}, a CFS slot "
        "such as 1B, or external"
    )


def slot_rule(text: str) -> SlotRule:
    """Return ``PATTERN=SLOT`` as a rule, raising ``ValueError`` if it is not one."""
    pattern, equals, slot = text.rpartition("=")
    if not equals or not pattern.strip():
        raise ValueError(f"'{text}' is not PATTERN=SLOT, for example '*_lens.stl=2'")
    return pattern.strip(), slot_value(slot)


def slot_for(model: Path, root: Path, rules: Sequence[SlotRule]) -> str:
    """Return the slot of the first rule ``model`` matches, or ``"1"``."""
    for pattern, slot in rules:
        for rule in normalise([pattern]):
            if path_matches(model, root, rule):
                return slot
    return "1"


def is_loaded_slot(slot: str) -> bool:
    """Return whether ``slot`` names a loaded filament (``1B``, ``external``), not a number."""
    return not slot.isdigit()


@dataclass(frozen=True, slots=True)
class SliceOptions:
    """How every model in a run is sliced."""

    orient: OrientMode = "off"
    allow_newer_files: bool = False
    """Let the slicer open 3MF projects saved by a newer slicer version."""

    thumbnails: bool = True
    """Add preview pictures, drawn from the G-code, for printer screens."""

    name_details: bool = True
    """Add the material and print time to G-code names, ``bracket_PETG_2h50m.gcode``."""

    plates: bool = False
    """Slice the loose models of each folder together, arranged on as few plates as fit."""

    copies: int = 1
    """How many copies of a single model to slice, arranged on as many plates as needed."""

    slots: tuple[SlotRule, ...] = ()
    """Filament slots for loose models (``--slot PATTERN=SLOT``), first match wins."""

    flat: bool = True
    """Put a batch's G-code straight into its folder; False mirrors its subfolders (``--folders``)."""

    def describe(self) -> str:
        """Return the options that differ from the defaults, as one line ("" if none)."""
        parts = []
        if self.orient == "retry":
            parts.append("auto-orient models that fail")
        elif self.orient == "always":
            parts.append("auto-orient every model")
        if self.allow_newer_files:
            parts.append("allow newer 3MF files")
        if self.copies > 1:
            parts.append(f"{self.copies} copies")
        if self.plates:
            parts.append("each folder's models together on plates")
        if not self.thumbnails:
            parts.append("no preview pictures")
        if not self.name_details:
            parts.append("no material or print time in names")
        if not self.flat:
            parts.append("G-code in mirrored folders")
        if self.slots:
            parts.append(
                "slots " + ", ".join(f"{pattern} -> {slot}" for pattern, slot in self.slots)
            )
        return ", ".join(parts)


def orient_mode(value: str) -> OrientMode:
    """Return ``value`` as an orient mode, raising ``ValueError`` if it is not one."""
    for mode in ORIENT_MODES:
        if value.strip().casefold() == mode:
            return mode
    raise ValueError(f"unknown orient mode '{value}' (choose from {', '.join(ORIENT_MODES)})")
