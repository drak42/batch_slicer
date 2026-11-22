"""Filaments loaded in a printer, and matching a project's colours to them.

A multi-material unit (Creality's CFS) reports what is loaded in each slot:
its colour and material. A multi-colour project lists the colour (and often
material) of each of its filament slots. Matching gives each project slot the
loaded filament that looks most alike, preferring the same material and using
each loaded filament once while there are enough of them. This module only
describes and matches; it does not talk to printers.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from batchslicer.domain.colours import colour_distance, colour_name, parse_colour

_MATERIAL_PENALTY = 120.0
"""Added to the colour distance when the materials differ (a clear colour difference)."""

_REUSE_PENALTY = 400.0
"""Added for a loaded filament already given to another project slot."""


@dataclass(frozen=True, slots=True)
class ProjectFilament:
    """One filament slot of a 3MF project."""

    colour: str
    """``#RRGGBB``, or ``""`` when the project gives none."""

    material: str = ""
    """Such as ``PLA`` or ``PETG``; ``""`` when the project gives none."""

    name: str = ""
    """The project's filament preset, such as ``Bambu PETG HF @BBL X1C``."""


@dataclass(frozen=True, slots=True)
class LoadedFilament:
    """One filament loaded in a printer."""

    slot: str
    """Where it is, as the printer names it: ``1A`` (CFS 1, slot A) or ``external``."""

    colour: str
    """``#RRGGBB``."""

    material: str = ""
    """Such as ``PETG``; ``""`` when the printer does not say."""

    def describe(self) -> str:
        """Return the slot, colour and material as shown to the user."""
        where = "external spool" if self.slot == "external" else f"CFS {self.slot}"
        what = " ".join(part for part in (colour_name(self.colour), self.material) if part)
        return f"{where} {what}".strip()


def describe_project_slot(slot: ProjectFilament) -> str:
    """Return a project slot's colour and material, such as ``black PETG``."""
    return " ".join(part for part in (colour_name(slot.colour), slot.material) if part) or "?"


def match_slots(
    project: Sequence[ProjectFilament], loaded: Sequence[LoadedFilament]
) -> list[int]:
    """Return, for each project slot, the index of the loaded filament it uses.

    Pairs are chosen best first (smallest difference in colour, then
    material). Each loaded filament is used once while there are loaded
    filaments left; after that the closest is reused. ``loaded`` must not be
    empty.
    """
    if not loaded:
        raise ValueError("No loaded filaments to match against.")
    costs = [[_cost(slot, filament) for filament in loaded] for slot in project]
    chosen: dict[int, int] = {}
    used: set[int] = set()
    pairs = sorted(
        (cost, slot, index)
        for slot, row in enumerate(costs)
        for index, cost in enumerate(row)
    )
    for _, slot, index in pairs:
        if slot in chosen or index in used:
            continue
        chosen[slot] = index
        used.add(index)
        if len(used) == len(loaded):
            break
    for slot, row in enumerate(costs):
        if slot not in chosen:
            chosen[slot] = min(range(len(row)), key=lambda index: row[index] + _REUSE_PENALTY * (index in used))
    return [chosen[slot] for slot in range(len(project))]


def _cost(slot: ProjectFilament, filament: LoadedFilament) -> float:
    """Return how poor a match ``filament`` is for ``slot`` (lower is better)."""
    wanted = parse_colour(slot.colour)
    have = parse_colour(filament.colour)
    cost = colour_distance(wanted, have) if wanted and have else 300.0
    if slot.material and filament.material and slot.material.casefold() != filament.material.casefold():
        cost += _MATERIAL_PENALTY
    return cost
