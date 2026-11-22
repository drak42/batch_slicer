"""Ask the user what to slice: one model file, or every model in a folder tree.

Model files and folders under the incoming folder are offered as numbered,
searchable lists, and a path anywhere else can be typed instead. A folder
includes all of its subfolders, minus anything matching ``--exclude``
patterns (:func:`exclude_models`). This module only handles the conversation
and finding candidate files; it does not slice.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from batchslicer.cli.menu import choose, confirm
from batchslicer.cli.slicer_prompt import SlicerSelectionError

MODEL_SUFFIXES = frozenset({".stl", ".3mf", ".obj"})
"""File types the slicers' command lines accept as models."""

_SUPPORTED = ", ".join(sorted(MODEL_SUFFIXES))


@dataclass(frozen=True, slots=True)
class SliceInput:
    """The model files chosen for slicing and where they were found."""

    root: Path
    """The chosen folder, or the folder holding the chosen file."""

    models: tuple[Path, ...]
    is_folder: bool


def exclude_models(chosen: SliceInput, patterns: Sequence[str]) -> tuple[SliceInput, int]:
    """Return ``chosen`` without the models matching ``patterns``, and how many were removed.

    Patterns use shell wildcards (``*``, ``?``, ``[...]``) and ignore case. A
    pattern without ``/`` matches any folder or file name at any depth
    (``Cura-*``, ``*_old.stl``); a pattern with ``/`` matches a path within
    the chosen folder (``kits/old``, ``*/supports/*``). A single chosen file
    is never excluded.
    """
    rules = [pattern.strip().strip("/").casefold() for pattern in patterns if pattern.strip().strip("/")]
    if not rules or not chosen.is_folder:
        return chosen, 0
    kept = tuple(model for model in chosen.models if not _excluded(model, chosen.root, rules))
    return replace(chosen, models=kept), len(chosen.models) - len(kept)


def _excluded(model: Path, root: Path, rules: list[str]) -> bool:
    """Return whether ``model`` (inside ``root``) matches any of the lower-cased ``rules``."""
    try:
        relative = PurePosixPath(model.relative_to(root).as_posix().casefold())
    except ValueError:
        return False
    # The model's path and each folder it is in, e.g. "kits", "kits/old", "kits/old/a.stl".
    prefixes = [PurePosixPath(*relative.parts[:depth]) for depth in range(1, len(relative.parts) + 1)]
    for rule in rules:
        if "/" in rule:
            if any(fnmatchcase(str(prefix), rule) for prefix in prefixes):
                return True
        elif any(fnmatchcase(part, rule) for part in relative.parts):
            return True
    return False


def find_models(directory: Path, *, recursive: bool = False) -> list[Path]:
    """Return model files in ``directory`` (and subfolders if ``recursive``), sorted.

    Hidden files and folders (names starting with ".") are skipped.
    """
    if not directory.is_dir():
        return []
    candidates = directory.rglob("*") if recursive else directory.iterdir()
    models = [
        path
        for path in candidates
        if is_model_file(path) and not _is_hidden(path.relative_to(directory))
    ]
    return sorted(models, key=lambda path: str(path.relative_to(directory)).casefold())


def find_folders(directory: Path) -> list[Path]:
    """Return ``directory`` and every non-hidden folder beneath it, sorted."""
    if not directory.is_dir():
        return []
    folders = [
        path
        for path in directory.rglob("*")
        if path.is_dir() and not _is_hidden(path.relative_to(directory))
    ]
    return [directory] + sorted(
        folders, key=lambda path: str(path.relative_to(directory)).casefold()
    )


def is_model_file(path: Path) -> bool:
    """Return whether ``path`` is an existing file of a supported model type."""
    return path.suffix.lower() in MODEL_SUFFIXES and path.is_file()


def input_from_path(path: Path) -> SliceInput:
    """Return the models for a path given on the command line.

    A model file is sliced on its own; a folder means every model in it and its
    subfolders. Raises :class:`SlicerSelectionError` if there is nothing to slice.
    """
    path = path.expanduser().absolute()
    if path.is_dir():
        models = find_models(path, recursive=True)
        if not models:
            raise SlicerSelectionError(
                f"No model files ({_SUPPORTED}) found in {path} or its subfolders."
            )
        return SliceInput(root=path, models=tuple(models), is_folder=True)
    if is_model_file(path):
        return SliceInput(root=path.parent, models=(path,), is_folder=False)
    if path.exists():
        raise SlicerSelectionError(f"Not a {_SUPPORTED} model file: {path}")
    raise SlicerSelectionError(f"Input not found: {path}")


def prompt_for_input(
    incoming: Path,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> SliceInput:
    """Ask whether to slice one file or a folder, then which, and return the models."""
    single = "One model file"
    folder = "Every model in a folder (including subfolders)"
    mode = choose(
        [single, folder],
        noun="option",
        plural="options",
        label=str,
        read_line=read_line,
        write=write,
        prompt="Enter 1-2: ",
        heading="What would you like to slice?",
    )
    if mode == single:
        model = prompt_for_model(incoming, read_line=read_line, write=write)
        return SliceInput(root=model.parent, models=(model,), is_folder=False)
    return prompt_for_folder(incoming, read_line=read_line, write=write)


def prompt_for_model(
    incoming: Path,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> Path:
    """Return the absolute path of the model file the user chooses.

    Models in the incoming folder and its subfolders are listed by their path
    within it (``brackets/left.stl``). Text that names an existing model file
    is used directly; any other text searches the list.
    Raises :class:`SlicerSelectionError` when input ends or is interrupted.
    """
    models = find_models(incoming, recursive=True)
    if not models:
        write(f"No model files ({_SUPPORTED}) found in {incoming}.")

    def accept_path(text: str) -> Path | None:
        path = Path(text).expanduser()
        if is_model_file(path):
            return path
        if path.exists():
            write(f"Not a {_SUPPORTED} model file: {text}")
        return None

    def label(path: Path) -> str:
        return path.relative_to(incoming).as_posix()

    chosen = choose(
        models,
        noun="model file",
        plural="model files",
        label=label,
        read_line=read_line,
        write=write,
        prompt=(
            "Model number, text to search, or a file path: "
            if models
            else "Path to a model file: "
        ),
        accept_text=accept_path,
    )
    return chosen.absolute()


def prompt_for_folder(
    incoming: Path,
    *,
    read_line: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> SliceInput:
    """Ask for a folder with models in it (subfolders included) and confirm the batch.

    Raises :class:`SlicerSelectionError` when input ends, is interrupted, or the
    user declines to slice the files found.
    """
    counts = {path: len(find_models(path, recursive=True)) for path in find_folders(incoming)}
    folders = [path for path, count in counts.items() if count]
    if not folders:
        write(f"No folders with model files ({_SUPPORTED}) found in {incoming}.")

    def label(path: Path) -> str:
        count = counts[path]
        name = incoming.name if path == incoming else f"{incoming.name}/{path.relative_to(incoming)}"
        return f"{name}  ({count} model{'s' if count != 1 else ''})"

    def accept_path(text: str) -> Path | None:
        path = Path(text).expanduser()
        if path.is_dir():
            return path
        if path.exists() or "/" in text or "\\" in text:
            write(f"Not a folder: {text}")
        return None

    while True:
        chosen = choose(
            folders,
            noun="folder",
            plural="folders",
            label=label,
            read_line=read_line,
            write=write,
            prompt=(
                "Folder number, text to search, or a folder path: "
                if folders
                else "Path to a folder: "
            ),
            accept_text=accept_path,
        ).absolute()
        models = find_models(chosen, recursive=True)
        if not models:
            write(f"No model files ({_SUPPORTED}) found in {chosen} or its subfolders.")
            continue
        count = f"{len(models)} model file{'s' if len(models) != 1 else ''}"
        if confirm(
            f"Slice {count} from {chosen} and its subfolders?",
            read_line=read_line,
            write=write,
        ):
            return SliceInput(root=chosen, models=tuple(models), is_folder=True)
        raise SlicerSelectionError("Batch cancelled.")


def _is_hidden(relative: Path) -> bool:
    """Return whether any part of ``relative`` is a hidden file or folder."""
    return any(part.startswith(".") for part in relative.parts)
