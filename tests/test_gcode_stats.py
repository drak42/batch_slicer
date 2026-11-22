"""Tests for reading print time and filament from G-code."""

from pathlib import Path

import pytest

from batchslicer.services.gcode_stats import (
    GcodeStats,
    format_duration,
    parse_duration,
    read_gcode_stats,
    total_stats,
)

ORCA_FOOTER = """G1 X1
; filament used [mm] = 2485.84
; filament used [cm3] = 5.98
; filament used [g] = 7.41
; filament cost = 0.15
; total filament used [g] = 7.41
; total filament cost = 0.15
; estimated printing time (normal mode) = 1d 2h 12m 10s
; CONFIG_BLOCK_START
; filament_density: 1.24
"""

BAMBU_HEADER = """; HEADER_BLOCK_START
; model printing time: 11m 2s; total estimated time: 12m 10s
; total filament length [mm] : 1200.50,300.00
; total filament weight [g] : 3.50,1.25
; HEADER_BLOCK_END
G1 X1
"""


def test_orcaslicer_statistics_are_read(tmp_path: Path) -> None:
    """OrcaSlicer's footer gives time, weight, length and cost."""
    gcode = tmp_path / "part.gcode"
    gcode.write_text(ORCA_FOOTER)

    stats = read_gcode_stats(gcode)

    assert stats == GcodeStats(94330.0, 7.41, 2485.84, 0.15)


def test_bambu_header_with_several_filaments_is_totalled(tmp_path: Path) -> None:
    """Bambu Studio's header lists one value per filament; they are added up."""
    gcode = tmp_path / "part.gcode"
    gcode.write_text(BAMBU_HEADER)

    stats = read_gcode_stats(gcode)

    assert stats.print_seconds == 730
    assert stats.filament_grams == pytest.approx(4.75)
    assert stats.filament_millimetres == pytest.approx(1500.5)
    assert stats.filament_cost is None


def test_statistics_far_from_the_ends_of_large_files_are_found(tmp_path: Path) -> None:
    """Only the start and end of big files are read, which is where slicers write them."""
    gcode = tmp_path / "big.gcode"
    gcode.write_text("G1 X1 Y1\n" * 200_000 + ORCA_FOOTER)

    assert read_gcode_stats(gcode).filament_grams == 7.41


def test_missing_or_unreadable_files_give_empty_statistics(tmp_path: Path) -> None:
    """No statistics is not an error."""
    assert read_gcode_stats(tmp_path / "missing.gcode") == GcodeStats()
    plain = tmp_path / "plain.gcode"
    plain.write_text("G1 X1\n")
    assert read_gcode_stats(plain) == GcodeStats()


def test_plates_are_totalled(tmp_path: Path) -> None:
    """A multi-plate project's statistics are the sum of its plates."""
    first = tmp_path / "a.gcode"
    second = tmp_path / "b.gcode"
    first.write_text(ORCA_FOOTER)
    second.write_text("; total filament used [g] = 2.59\n")

    total = total_stats([first, second])

    assert total.filament_grams == pytest.approx(10.0)
    assert total.print_seconds == 94330.0


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("12m 10s", 730), ("1h 0m 5s", 3605), ("2d 1h", 176400), ("45s", 45), ("n/a", None)],
)
def test_durations_are_parsed(text: str, seconds: float | None) -> None:
    """Slicer durations use d, h, m and s parts."""
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    ("seconds", "text"), [(730, "12m"), (3605, "1h 0m"), (176400, "2d 1h 0m"), (20, "0m")]
)
def test_durations_are_formatted(seconds: float, text: str) -> None:
    """Durations are shown to the minute."""
    assert format_duration(seconds) == text
