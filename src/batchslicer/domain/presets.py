"""Describe slicer presets and the set of presets chosen for a slicing run.

These are plain value objects shared by the backends that read presets and the
CLI that lets users choose them. This module does not read files, resolve
inheritance, or talk to slicers.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PresetKind(Enum):
    """The three kinds of preset a slice needs, valued by the slicer's folder name."""

    PRINTER = "machine"
    FILAMENT = "filament"
    PROCESS = "process"

    @property
    def label(self) -> str:
        """Return the user-facing name of this preset kind."""
        return self.name.capitalize()


@dataclass(frozen=True, slots=True)
class Preset:
    """Identify one preset file in a slicer's data directory."""

    name: str
    kind: PresetKind
    path: Path
    is_user: bool
    """True for presets the user saved, False for presets shipped with the slicer."""


@dataclass(frozen=True, slots=True)
class PresetSelection:
    """The printer, filament and process presets chosen for slicing."""

    printer: Preset
    filament: Preset
    """The filament for slot 1 (the only one, for a single-material print)."""

    process: Preset
    more_filaments: tuple[Preset, ...] = ()
    """Filaments for slots 2, 3... of a multi-material printer, when chosen."""

    @property
    def filaments(self) -> tuple[Preset, ...]:
        """Return the filament of every chosen slot, slot 1 first."""
        return (self.filament, *self.more_filaments)
