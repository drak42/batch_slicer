"""Run ``batchslicer setup``: detect slicers and write the configuration file.

For each supported slicer, the installed copies are found, the recommended one
is offered first (the user may pick another version or skip the slicer), and
the slicer's settings folder is located. The chosen slicers are written to the
configuration file, an existing file is only replaced after confirmation (or
with ``--force``) and is kept as a ``.bak`` copy, and the default model and
output folders are created. This module handles the conversation; detection
and the file's contents come from other modules.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from batchslicer.backends.detection import (
    Installation,
    find_data_directory,
    find_installations,
)
from batchslicer.backends.slicers import SLICERS, SlicerDefinition
from batchslicer.cli.menu import confirm
from batchslicer.cli.slicer_prompt import SlicerSelectionError
from batchslicer.core.config import render_config
from batchslicer.core.locations import default_paths


@dataclass(frozen=True, slots=True)
class SetupOptions:
    """Options for ``batchslicer setup``."""

    config: Path
    """Configuration file to write."""

    no_prompt: bool = False
    force: bool = False


def run_setup(
    options: SetupOptions,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Detect slicers, write the configuration file and return its path.

    Raises :class:`SlicerSelectionError` if setup is cancelled, the file exists
    and may not be replaced, or no usable slicer is found.
    """
    target = options.config.expanduser().absolute()
    prompt = not options.no_prompt
    write(f"Configuration file: {target}")
    _check_target(target, options, read_line, write)

    chosen: dict[str, tuple[Path, Path]] = {}
    for slicer in SLICERS:
        installations = find_installations(slicer.key, home=home, environ=environ)
        if not installations:
            write(f"{slicer.display_name}: not found.")
            continue
        if find_data_directory(slicer.key, home=home, environ=environ) is None:
            write(
                f"{slicer.display_name}: found {installations[0].executable.name}, but it "
                "has not been opened yet. Open it once, add your printers, then run "
                "'batchslicer setup' again to include it."
            )
            continue
        installation = (
            _choose_installation(slicer, installations, read_line, write)
            if prompt
            else installations[0]
        )
        if installation is None:
            write(f"{slicer.display_name}: skipped.")
            continue
        data_directory = find_data_directory(
            slicer.key, installation, home=home, environ=environ
        )
        if data_directory is None:
            write(
                f"{slicer.display_name}: found {installation.executable.name}, but it has "
                "not been opened yet. Open it once, add your printers, then run "
                "'batchslicer setup' again to include it."
            )
            continue
        write(
            f"{slicer.display_name}: {installation.executable} "
            f"(version {installation.version_text}), settings in {data_directory}"
        )
        chosen[slicer.key] = (installation.executable, data_directory)

    if not chosen:
        raise SlicerSelectionError(
            "No usable slicer was found. Install OrcaSlicer, Creality Print or Bambu "
            "Studio (an AppImage in ~/Apps works), open it once, then run setup again."
        )

    _write_config(target, render_config(chosen, home=home))
    folders = default_paths(environ)
    for key in ("incoming", "output"):
        folders[key].mkdir(parents=True, exist_ok=True)

    write("")
    write(f"Saved {target}")
    write(f"Put models to slice in {folders['incoming']}; results go to {folders['output']}.")
    write("Run 'batchslicer' to start slicing.")
    return target


def _check_target(
    target: Path,
    options: SetupOptions,
    read_line: Callable[[str], str],
    write: Callable[[str], None],
) -> None:
    """Make sure an existing configuration file may be replaced."""
    if not target.exists():
        return
    if options.force:
        return
    if options.no_prompt:
        raise SlicerSelectionError(
            f"{target} already exists. Use --force to replace it (a backup is kept)."
        )
    if not confirm(
        f"{target} already exists. Replace it? (a backup is kept as {target.name}.bak)",
        read_line=read_line,
        write=write,
        default=False,
    ):
        raise SlicerSelectionError("Setup cancelled; the existing configuration was kept.")


def _choose_installation(
    slicer: SlicerDefinition,
    installations: list[Installation],
    read_line: Callable[[str], str],
    write: Callable[[str], None],
) -> Installation | None:
    """Ask which copy of a slicer to use; Enter takes the recommended one."""
    write(f"{slicer.display_name}:")
    for number, installation in enumerate(installations, start=1):
        notes = [f"version {installation.version_text}"]
        if installation.prerelease:
            notes.append("pre-release")
        if number == 1:
            notes.append("recommended")
        write(f"  {number}) {installation.executable}  ({', '.join(notes)})")
    skip = len(installations) + 1
    write(f"  {skip}) Don't use {slicer.display_name}")

    while True:
        try:
            answer = read_line(f"Enter for 1, or a number 1-{skip}: ").strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError("Setup cancelled.") from error
        if not answer:
            return installations[0]
        if answer.isdigit() and 1 <= int(answer) <= skip:
            number = int(answer)
            return None if number == skip else installations[number - 1]
        write(f"Please enter a number from 1 to {skip}.")


def _write_config(target: Path, text: str) -> None:
    """Write the configuration file, keeping any existing one as a backup."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name(target.name + ".bak")
        backup.write_bytes(target.read_bytes())
    target.write_text(text, encoding="utf-8")
