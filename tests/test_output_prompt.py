"""Tests for choosing or creating the output folder."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from batchslicer.cli.output_prompt import find_destinations, prompt_for_output
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
def output(tmp_path: Path) -> Path:
    """Create an output folder with destinations and earlier job folders."""
    root = tmp_path / "output"
    for name in ("k2-batch", "Archive", "cube-20261120-144428", "parts-20261120-144428-2", ".trash"):
        (root / name).mkdir(parents=True)
    (root / "notes.txt").write_text("x")
    return root


def test_destinations_exclude_job_folders_and_hidden_ones(output: Path) -> None:
    """Earlier job folders and hidden folders are not offered."""
    assert [path.name for path in find_destinations(output)] == ["output", "Archive", "k2-batch"]


def test_enter_uses_the_default_output_folder(output: Path) -> None:
    """Pressing Enter picks the configured output folder."""
    lines: list[str] = []

    chosen = prompt_for_output(output, read_line=_answers(""), write=lines.append)

    assert chosen == output.absolute()
    assert lines == [
        "Select an output folder:",
        "  1) output  (default)",
        "  2) output/Archive",
        "  3) output/k2-batch",
    ]


def test_number_picks_an_existing_subfolder(output: Path) -> None:
    """A number picks one of the listed folders."""
    assert prompt_for_output(output, read_line=_answers("3"), write=lambda _: None) == (
        output / "k2-batch"
    ).absolute()


def test_existing_name_is_used_without_asking(output: Path) -> None:
    """Typing the name of an existing subfolder uses it directly."""
    chosen = prompt_for_output(output, read_line=_answers("Archive"), write=lambda _: None)

    assert chosen == (output / "Archive").absolute()


def test_new_name_is_created_inside_output_after_confirming(output: Path) -> None:
    """A new plain name becomes a folder inside the output folder once confirmed."""
    lines: list[str] = []

    chosen = prompt_for_output(output, read_line=_answers("ender/pla", "y"), write=lines.append)

    assert chosen == (output / "ender" / "pla").absolute()
    assert chosen.is_dir()


def test_absolute_path_is_created_where_typed(output: Path, tmp_path: Path) -> None:
    """An absolute path is used as typed, not placed inside the output folder."""
    target = tmp_path / "elsewhere" / "gcode"

    chosen = prompt_for_output(output, read_line=_answers(str(target), ""), write=lambda _: None)

    assert chosen == target
    assert target.is_dir()


def test_declining_creation_asks_again(output: Path) -> None:
    """Saying no to creating a folder returns to the question."""
    chosen = prompt_for_output(output, read_line=_answers("new", "n", "1"), write=lambda _: None)

    assert chosen == output.absolute()
    assert not (output / "new").exists()


def test_files_and_bad_numbers_are_refused(output: Path) -> None:
    """A file is not a folder, and numbers must be in range."""
    lines: list[str] = []

    prompt_for_output(output, read_line=_answers("notes.txt", "9", "2"), write=lines.append)

    assert any(line.startswith("Not a folder:") for line in lines)
    assert "Please enter a number from 1 to 3." in lines


def test_missing_default_folder_can_be_created(tmp_path: Path) -> None:
    """If the configured output folder is missing, Enter offers to create it."""
    root = tmp_path / "not-yet"

    chosen = prompt_for_output(root, read_line=_answers("", "y"), write=lambda _: None)

    assert chosen == root.absolute()
    assert root.is_dir()


def test_end_of_input_stops_selection(output: Path) -> None:
    """Closing input stops instead of looping."""
    with pytest.raises(SlicerSelectionError, match="No output folder selected"):
        prompt_for_output(output, read_line=_answers(), write=lambda _: None)
