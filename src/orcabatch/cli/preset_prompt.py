"""Ask the user to choose the printer, filament and process presets for a run.

The printer is chosen first, because it decides which filament and process
presets are compatible. Long lists can be narrowed by typing part of a name.
This module only handles the conversation; it does not read preset files.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from orcabatch.cli.menu import choose
from orcabatch.cli.slicer_prompt import SlicerSelectionError
from orcabatch.domain.presets import Preset, PresetKind, PresetSelection


class PresetSource(Protocol):
    """Provide the presets offered to the user."""

    def printers(self) -> list[Preset]:
        """Return the printers the user can choose from."""
        ...

    def filaments_for(self, printer: Preset) -> list[Preset]:
        """Return the filaments compatible with ``printer``."""
        ...

    def processes_for(self, printer: Preset) -> list[Preset]:
        """Return the process presets compatible with ``printer``."""
        ...


def prompt_for_presets(
    source: PresetSource,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> PresetSelection:
    """Ask for a printer, then a compatible filament and process, and return them.

    Raises :class:`SlicerSelectionError` when a list is empty or input ends.
    """
    printer = choose_preset(PresetKind.PRINTER, source.printers(), read_line, write)
    filament = choose_preset(
        PresetKind.FILAMENT, source.filaments_for(printer), read_line, write
    )
    process = choose_preset(
        PresetKind.PROCESS, source.processes_for(printer), read_line, write
    )
    return PresetSelection(printer=printer, filament=filament, process=process)


def choose_preset(
    kind: PresetKind,
    presets: Sequence[Preset],
    read_line: Callable[[str], str],
    write: Callable[[str], None],
) -> Preset:
    """Show ``presets`` as a numbered, searchable list and return the one picked."""
    name = kind.label.lower()
    if not presets:
        raise SlicerSelectionError(f"No compatible {name} presets were found.")
    return choose(
        presets,
        noun=name,
        plural=f"{name} presets",
        label=_label,
        read_line=read_line,
        write=write,
        prompt=f"{kind.label} number, or text to search: ",
    )


def _label(preset: Preset) -> str:
    """Return the menu text for a preset, marking the user's own."""
    return f"{preset.name}  (mine)" if preset.is_user else preset.name
