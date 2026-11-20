"""Ask the user where sliced results should go, creating the folder if needed.

The configured output folder is the default. Its existing subfolders are
offered by number, and any other folder can be named: a plain name is created
inside the output folder, while an absolute or ``~`` path is used as typed.
Folders that do not exist are created only after the user confirms. Job folders
OrcaBatch created earlier are not offered as destinations.
"""

from collections.abc import Callable
from pathlib import Path
import re

from orcabatch.cli.menu import confirm
from orcabatch.cli.slicer_prompt import SlicerSelectionError


_JOB_FOLDER_PATTERN = re.compile(r"-\d{8}-\d{6}(-\d+)?$")
"""Names of job folders created by the slicing service (``<name>-YYYYMMDD-HHMMSS``)."""


def find_destinations(output_root: Path) -> list[Path]:
    """Return ``output_root`` and its subfolders that are not earlier job folders."""
    if not output_root.is_dir():
        return [output_root]
    subfolders = sorted(
        (
            path
            for path in output_root.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and not _JOB_FOLDER_PATTERN.search(path.name)
        ),
        key=lambda path: path.name.casefold(),
    )
    return [output_root, *subfolders]


def prompt_for_output(
    output_root: Path,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> Path:
    """Return the absolute output folder the user chooses, creating it if confirmed.

    Raises :class:`SlicerSelectionError` when input ends or is interrupted.
    """
    destinations = find_destinations(output_root)
    write("Select an output folder:")
    for number, path in enumerate(destinations, start=1):
        name = output_root.name if path == output_root else f"{output_root.name}/{path.name}"
        default = "  (default)" if path == output_root else ""
        write(f"  {number}) {name}{default}")

    while True:
        try:
            answer = read_line(
                "Folder number, a new folder name or path, or Enter for the default: "
            ).strip()
        except (EOFError, KeyboardInterrupt) as error:
            write("")
            raise SlicerSelectionError("No output folder selected.") from error

        if not answer:
            chosen = output_root
        elif answer.isdigit():
            number = int(answer)
            if not 1 <= number <= len(destinations):
                write(f"Please enter a number from 1 to {len(destinations)}.")
                continue
            chosen = destinations[number - 1]
        else:
            typed = Path(answer).expanduser()
            chosen = typed if typed.is_absolute() else output_root / typed

        chosen = chosen.absolute()
        if chosen.is_dir():
            return chosen
        if chosen.exists():
            write(f"Not a folder: {chosen}")
            continue
        if not confirm(f"Create {chosen}?", read_line=read_line, write=write):
            continue
        try:
            chosen.mkdir(parents=True)
        except OSError as error:
            write(f"Could not create {chosen}: {error}")
            continue
        return chosen
