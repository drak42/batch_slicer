"""Slice multi-colour projects with the filaments loaded in the printer.

With ``--loaded-filaments``, each slot of a multi-colour 3MF project is given
the loaded filament (CFS slot or external spool) whose colour and material
match it best (see :func:`batchslicer.domain.filaments.match_slots`). The
slot is sliced with a filament preset of the loaded material, coloured like
the loaded filament, so the G-code, its preview pictures and the printer's
screen all show the real colours. Models that are not multi-colour projects
are sliced with the chosen filaments as usual. This module writes the filament
files for each project; it does not read the printer or run the slicer.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from batchslicer.backends.presets import PresetError, PresetLibrary
from batchslicer.backends.projects import project_filaments
from batchslicer.domain.filaments import LoadedFilament, describe_project_slot, match_slots
from batchslicer.domain.presets import Preset, PresetSelection

_FOLDER = "presets"


@dataclass(frozen=True, slots=True)
class LoadedPreset:
    """A loaded filament and the preset it is sliced with."""

    loaded: LoadedFilament
    preset: Preset
    settings: dict[str, Any]
    """The preset's complete settings, coloured like the loaded filament."""


class FilamentMatcher:
    """Give each slot of a multi-colour project the loaded filament that matches it."""

    def __init__(self, loaded: Sequence[LoadedPreset], *, logger: logging.Logger) -> None:
        """Match against ``loaded`` (at least one)."""
        if not loaded:
            raise ValueError("A matcher needs at least one loaded filament.")
        self._loaded = list(loaded)
        self._logger = logger
        self.matches: dict[Path, tuple[str, ...]] = {}
        """For each project matched so far, one line per slot: which filament it uses."""

    @property
    def loaded(self) -> tuple[LoadedPreset, ...]:
        """Return the loaded filaments and their presets."""
        return tuple(self._loaded)

    def files_for(self, model: Path, job_directory: Path) -> list[Path] | None:
        """Return filament files for every slot of ``model``, or None if it is not multi-colour.

        The files are written into the job's ``presets`` folder, named after
        the loaded slot they stand for.
        """
        project = project_filaments(model)
        if len(project) < 2:
            return None
        choice = match_slots(project, [item.loaded for item in self._loaded])
        files: list[Path] = []
        lines: list[str] = []
        for number, (slot, index) in enumerate(zip(project, choice, strict=True), start=1):
            item = self._loaded[index]
            files.append(self._write(item, job_directory))
            lines.append(
                f"slot {number} ({describe_project_slot(slot)}) -> {item.loaded.describe()}"
                f" [{item.preset.name}]"
            )
        self.matches[model] = tuple(lines)
        self._logger.info("Matched %s to loaded filaments: %s", model.name, "; ".join(lines))
        return files


    def file_for_slot(self, slot: str, job_directory: Path) -> Path | None:
        """Return the filament file for one loaded slot (``1B``, ``external``), or None if empty."""
        for item in self._loaded:
            if item.loaded.slot.casefold() == slot.casefold():
                return self._write(item, job_directory)
        return None

    def _write(self, item: LoadedPreset, job_directory: Path) -> Path:
        """Write one loaded filament's file into the job's ``presets`` folder, once."""
        folder = job_directory / _FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"filament-{item.loaded.slot}.json"
        if not path.exists():
            path.write_text(json.dumps(item.settings, indent=4), encoding="utf-8")
        return path


def build_matcher(
    loaded: Sequence[LoadedFilament],
    library: PresetLibrary,
    selection: PresetSelection,
    *,
    logger: logging.Logger,
) -> FilamentMatcher | None:
    """Return a matcher for the ``loaded`` filaments, or None if nothing is loaded.

    Each loaded filament is sliced with a preset of its material: one of the
    chosen filaments if it is that material, else the user's own preset for it,
    else a "Generic" one, else any compatible one; when the material is unknown
    or no preset has it, the first chosen filament.
    """
    if not loaded:
        return None
    chooser = _PresetChooser(library, selection)
    items = [
        LoadedPreset(
            filament,
            preset := chooser.for_material(filament.material),
            library.resolve_filament(preset, colour=filament.colour),
        )
        for filament in loaded
    ]
    return FilamentMatcher(items, logger=logger)


class _PresetChooser:
    """Pick a filament preset for a material, remembering what each preset is."""

    def __init__(self, library: PresetLibrary, selection: PresetSelection) -> None:
        self._library = library
        self._selection = selection
        self._materials: dict[str, str] = {}
        self._compatible: list[Preset] | None = None

    def for_material(self, material: str) -> Preset:
        if not material:
            return self._selection.filament
        wanted = material.casefold()
        for preset in self._selection.filaments:
            if self._material(preset) == wanted:
                return preset
        compatible = self._compatible_filaments()
        ordered = (
            [preset for preset in compatible if preset.is_user],
            [preset for preset in compatible if "generic" in preset.name.casefold()],
            compatible,
        )
        for group in ordered:
            for preset in group:
                if self._material(preset) == wanted:
                    return preset
        return self._selection.filament

    def _compatible_filaments(self) -> list[Preset]:
        if self._compatible is None:
            self._compatible = list(self._library.filaments_for(self._selection.printer))
        return self._compatible

    def _material(self, preset: Preset) -> str:
        if preset.name not in self._materials:
            try:
                value = self._library.resolve(preset).get("filament_type", "")
            except (PresetError, OSError, ValueError):  # an unreadable preset does not match
                value = ""
            if isinstance(value, list):
                value = value[0] if value else ""
            self._materials[preset.name] = str(value).casefold()
        return self._materials[preset.name]
