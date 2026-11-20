"""Ask the user to choose the printer, filament and process presets for a run.

The printer is chosen first, because it decides which filament and process
presets are compatible. Long lists can be narrowed by typing part of a name.
Presets named on the command line are looked up instead of asked for. This
module only handles choosing; it does not read preset files.
"""

import difflib
from collections.abc import Callable, Sequence
from typing import Protocol

from batchslicer.cli.menu import choose
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection


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
    return select_presets(source, read_line=read_line, write=write)


def select_presets(
    source: PresetSource,
    *,
    printer: str | None = None,
    filament: str | None = None,
    process: str | None = None,
    prompt: bool = True,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> PresetSelection:
    """Return the named presets, asking for any not named when ``prompt`` is true.

    Raises :class:`SlicerSelectionError` when a name does not match a compatible
    preset, or a preset is not named and ``prompt`` is false.
    """
    chosen_printer = _named_or_chosen(
        PresetKind.PRINTER, source.printers(), printer, prompt, read_line, write
    )
    chosen_filament = _named_or_chosen(
        PresetKind.FILAMENT,
        source.filaments_for(chosen_printer),
        filament,
        prompt,
        read_line,
        write,
        printer=chosen_printer,
    )
    chosen_process = _named_or_chosen(
        PresetKind.PROCESS,
        source.processes_for(chosen_printer),
        process,
        prompt,
        read_line,
        write,
        printer=chosen_printer,
    )
    return PresetSelection(
        printer=chosen_printer, filament=chosen_filament, process=chosen_process
    )


def find_preset(
    kind: PresetKind,
    presets: Sequence[Preset],
    name: str,
    *,
    printer: Preset | None = None,
) -> Preset:
    """Return the preset called ``name`` (ignoring case) from ``presets``.

    Raises :class:`SlicerSelectionError` naming close matches when there is none.
    """
    wanted = name.strip().casefold()
    for preset in presets:
        if preset.name.casefold() == wanted:
            return preset

    where = f" compatible with {printer.name}" if printer is not None else ""
    message = f"No {kind.label.lower()} preset named '{name}'{where}."
    names = [preset.name for preset in presets]
    suggestions = difflib.get_close_matches(name, names, n=3, cutoff=0.5)
    suggestions += [
        candidate
        for candidate in names
        if wanted in candidate.casefold() and candidate not in suggestions
    ][: 3 - len(suggestions)]
    if suggestions:
        message += " Did you mean: " + "; ".join(f"'{item}'" for item in suggestions) + "?"
    message += " Use --list-presets to see all names."
    raise SlicerSelectionError(message)


def _named_or_chosen(
    kind: PresetKind,
    presets: Sequence[Preset],
    name: str | None,
    prompt: bool,
    read_line: Callable[[str], str],
    write: Callable[[str], None],
    *,
    printer: Preset | None = None,
) -> Preset:
    """Return the named preset, or ask for one, or fail when asking is not allowed."""
    if name is not None:
        return find_preset(kind, presets, name, printer=printer)
    if not prompt:
        option = "--" + kind.label.lower()
        raise SlicerSelectionError(f"{option} is required when --no-prompt is used.")
    return choose_preset(kind, presets, read_line, write)


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
