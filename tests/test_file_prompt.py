"""Tests for choosing the model file to slice."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from batchslicer.cli.file_prompt import (
    find_models,
    input_from_path,
    prompt_for_folder,
    prompt_for_input,
    prompt_for_model,
)
from batchslicer.cli.slicer_prompt import SlicerSelectionError


def _answers(*values: str) -> Callable[[str], str]:
    """Return a read_line replacement that yields ``values`` in order."""
    iterator: Iterator[str] = iter(values)

    def read_line(prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read_line


@pytest.fixture
def incoming(tmp_path: Path) -> Path:
    """Create an incoming folder with models and other files."""
    folder = tmp_path / "incoming"
    folder.mkdir()
    for name in ("bracket.STL", "Arm.3mf", "gear.obj", "notes.txt", "cube.stl"):
        (folder / name).write_text("x")
    (folder / "subfolder.stl").mkdir()
    return folder


def test_find_models_lists_supported_files_by_name(incoming: Path) -> None:
    """Only .stl/.3mf/.obj files are found, case-insensitively, sorted by name."""
    assert [path.name for path in find_models(incoming)] == [
        "Arm.3mf",
        "bracket.STL",
        "cube.stl",
        "gear.obj",
    ]


def test_find_models_handles_missing_folder(tmp_path: Path) -> None:
    """A missing incoming folder has no models."""
    assert find_models(tmp_path / "missing") == []


def test_number_picks_a_model_from_incoming(incoming: Path) -> None:
    """Models are listed and a number picks one, returned as an absolute path."""
    lines: list[str] = []

    chosen = prompt_for_model(incoming, read_line=_answers("3"), write=lines.append)

    assert chosen == (incoming / "cube.stl").absolute()
    assert lines[:2] == ["Select a model file:", "  1) Arm.3mf"]


def test_text_searches_the_list(incoming: Path) -> None:
    """Text that is not a path narrows the list."""
    chosen = prompt_for_model(incoming, read_line=_answers("gear", "1"), write=lambda _: None)

    assert chosen.name == "gear.obj"


def test_a_path_outside_incoming_can_be_typed(incoming: Path, tmp_path: Path) -> None:
    """A path to a model file anywhere is accepted directly."""
    elsewhere = tmp_path / "elsewhere" / "part.3mf"
    elsewhere.parent.mkdir()
    elsewhere.write_text("x")

    chosen = prompt_for_model(incoming, read_line=_answers(str(elsewhere)), write=lambda _: None)

    assert chosen == elsewhere


def test_paths_that_are_not_models_are_refused(incoming: Path, tmp_path: Path) -> None:
    """Typed paths to missing or unsupported files are explained and asked again."""
    lines: list[str] = []

    prompt_for_model(
        incoming,
        read_line=_answers(str(tmp_path / "missing.stl"), str(incoming / "notes.txt"), "1"),
        write=lines.append,
    )

    assert sum(line.startswith("Not a .3mf, .obj, .stl model file:") for line in lines) == 2


def test_empty_incoming_asks_for_a_path(tmp_path: Path) -> None:
    """With nothing in incoming, the user is told and can type a path."""
    model = tmp_path / "model.stl"
    model.write_text("x")
    lines: list[str] = []

    chosen = prompt_for_model(
        tmp_path / "empty", read_line=_answers("nothing", str(model)), write=lines.append
    )

    assert chosen == model
    assert lines[0].startswith("No model files (.3mf, .obj, .stl) found in")


def test_end_of_input_stops_selection(incoming: Path) -> None:
    """Closing input stops instead of looping."""
    with pytest.raises(SlicerSelectionError, match="No model file selected"):
        prompt_for_model(incoming, read_line=_answers(), write=lambda _: None)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Create an incoming folder with nested model folders."""
    root = tmp_path / "incoming"
    for relative in (
        "top.stl",
        "brackets/left.stl",
        "brackets/right.3MF",
        "brackets/old/v1.obj",
        "empty/readme.txt",
        ".hidden/secret.stl",
        "brackets/.cache/tmp.stl",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return root


def test_recursive_find_includes_subfolders_and_skips_hidden(tree: Path) -> None:
    """Recursive search finds models at any depth but not in hidden folders."""
    found = [str(path.relative_to(tree)) for path in find_models(tree, recursive=True)]

    assert found == ["brackets/left.stl", "brackets/old/v1.obj", "brackets/right.3MF", "top.stl"]


def test_single_file_mode_returns_one_model(tree: Path) -> None:
    """Choosing 'one model file' asks for a file in the incoming folder."""
    chosen = prompt_for_input(tree, read_line=_answers("1", "1"), write=lambda _: None)

    assert not chosen.is_folder
    assert chosen.models == ((tree / "top.stl").absolute(),)
    assert chosen.root == tree.absolute()


def test_folder_mode_lists_folders_with_counts_and_slices_the_tree(tree: Path) -> None:
    """Folders containing models are listed with counts; the choice includes subfolders."""
    lines: list[str] = []

    chosen = prompt_for_input(tree, read_line=_answers("2", "2", ""), write=lines.append)

    assert lines[lines.index("Select a folder:") + 1 :][:3] == [
        "  1) incoming  (4 models)",
        "  2) incoming/brackets  (3 models)",
        "  3) incoming/brackets/old  (1 model)",
    ]
    assert "  4) incoming/empty  (0 models)" not in lines
    assert chosen.is_folder
    assert chosen.root == (tree / "brackets").absolute()
    assert [path.name for path in chosen.models] == ["left.stl", "v1.obj", "right.3MF"]


def test_folder_can_be_typed_as_a_path(tree: Path, tmp_path: Path) -> None:
    """Any folder can be typed, and the batch is confirmed before slicing."""
    other = tmp_path / "other"
    (other / "deep").mkdir(parents=True)
    (other / "deep" / "part.stl").write_text("x")
    lines: list[str] = []

    chosen = prompt_for_folder(tree, read_line=_answers(str(other), "y"), write=lines.append)

    assert chosen.root == other
    assert chosen.models == (other / "deep" / "part.stl",)


def test_folder_without_models_asks_again(tree: Path) -> None:
    """A typed folder with no models is explained and the question repeats."""
    lines: list[str] = []

    chosen = prompt_for_folder(
        tree, read_line=_answers(str(tree / "empty"), "1", "y"), write=lines.append
    )

    assert any("No model files" in line and "empty" in line for line in lines)
    assert chosen.root == tree.absolute()


def test_declining_the_batch_cancels(tree: Path) -> None:
    """Answering no to the confirmation stops without slicing."""
    with pytest.raises(SlicerSelectionError, match="Batch cancelled"):
        prompt_for_folder(tree, read_line=_answers("1", "n"), write=lambda _: None)


def test_input_path_to_a_folder_slices_the_whole_tree(tree: Path) -> None:
    """A folder given with --input includes every model beneath it, without asking."""
    chosen = input_from_path(tree / "brackets")

    assert chosen.is_folder
    assert [path.name for path in chosen.models] == ["left.stl", "v1.obj", "right.3MF"]


def test_input_path_to_a_model_slices_that_file(tree: Path) -> None:
    """A model file given with --input is sliced on its own."""
    chosen = input_from_path(tree / "top.stl")

    assert not chosen.is_folder
    assert chosen.models == ((tree / "top.stl").absolute(),)


@pytest.mark.parametrize(
    ("relative", "message"),
    [("missing.stl", "Input not found"), ("empty/readme.txt", "Not a"), ("empty", "No model files")],
)
def test_bad_input_paths_are_explained(tree: Path, relative: str, message: str) -> None:
    """Missing paths, non-model files and empty folders are refused with a reason."""
    with pytest.raises(SlicerSelectionError, match=message):
        input_from_path(tree / relative)
