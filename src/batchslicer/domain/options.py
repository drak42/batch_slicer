"""Describe how models are sliced, beyond the presets: orientation, file versions, pictures.

These options change what is asked of the slicer for every model in a run.
They are plain values shared by the command line, profiles and the slicing
service; this module does not run slicers.
"""

from dataclasses import dataclass
from typing import Literal, TypeAlias

OrientMode: TypeAlias = Literal["off", "retry", "always"]

ORIENT_MODES: tuple[OrientMode, ...] = ("off", "retry", "always")
"""When the slicer's auto-orient is used.

``off``: models are sliced as they were saved. ``retry``: a model that fails is
sliced once more with auto-orient. ``always``: every model is auto-oriented,
which may rotate parts that were saved in the orientation meant for printing.
"""

MAX_JOBS = 64
"""The most models that may be sliced at the same time."""


@dataclass(frozen=True, slots=True)
class SliceOptions:
    """How every model in a run is sliced."""

    orient: OrientMode = "off"
    allow_newer_files: bool = False
    """Let the slicer open 3MF projects saved by a newer slicer version."""

    thumbnails: bool = True
    """Add preview pictures, drawn from the G-code, for printer screens."""

    plates: bool = False
    """Slice the loose models of each folder together, arranged on as few plates as fit."""

    def describe(self) -> str:
        """Return the options that differ from the defaults, as one line ("" if none)."""
        parts = []
        if self.orient == "retry":
            parts.append("auto-orient models that fail")
        elif self.orient == "always":
            parts.append("auto-orient every model")
        if self.allow_newer_files:
            parts.append("allow newer 3MF files")
        if self.plates:
            parts.append("each folder's models together on plates")
        if not self.thumbnails:
            parts.append("no preview pictures")
        return ", ".join(parts)


def orient_mode(value: str) -> OrientMode:
    """Return ``value`` as an orient mode, raising ``ValueError`` if it is not one."""
    for mode in ORIENT_MODES:
        if value.strip().casefold() == mode:
            return mode
    raise ValueError(f"unknown orient mode '{value}' (choose from {', '.join(ORIENT_MODES)})")
