"""Tests for reading print time and filament from G-code."""

from pathlib import Path

import pytest

from batchslicer.services.gcode_stats import (
    GcodeStats,
    format_duration,
    name_details,
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

    assert stats == GcodeStats(94330.0, 7.41, 2485.84, 0.15, (7.41,))


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


def test_multi_material_statistics_are_read(tmp_path: Path) -> None:
    """Grams per filament and filament changes are read (OrcaSlicer and Bambu Studio wording)."""
    orca = tmp_path / "orca.gcode"
    orca.write_text(
        "G1 X1\n; filament used [g] = 13.78, 0.39\n; total filament used [g] = 14.17\n"
        "; total filament change = 36\n"
    )
    bambu = tmp_path / "bambu.gcode"
    bambu.write_text(
        "; total filament weight [g] : 10.66,0.29\nM620 S0A\nT0\nG1 X1\nT1 ; change\nT1\nT255\n"
        "T0\nT1000\nT0\nG1 X2\n"
    )

    stats = read_gcode_stats(orca)
    assert stats.grams_per_filament == (13.78, 0.39)
    assert stats.filament_changes == 36
    assert stats.used_filaments() == ((1, 13.78), (2, 0.39))
    assert read_gcode_stats(bambu).grams_per_filament == (10.66, 0.29)
    assert read_gcode_stats(bambu).filament_changes == 2  # counted: T0 -> T1 -> T0, other tools ignored

    both = stats + read_gcode_stats(bambu) + GcodeStats(grams_per_filament=(1.0, 0.0, 2.0))
    assert both.grams_per_filament == pytest.approx((25.44, 0.68, 2.0))
    assert both.filament_changes == 38


def test_unused_slots_are_not_counted_as_used() -> None:
    """A project listing five filaments but printing with one uses one."""
    assert GcodeStats(grams_per_filament=(7.4, 0.0, 0.0)).used_filaments() == ((1, 7.4),)


def test_single_material_files_are_not_scanned_for_changes(tmp_path: Path) -> None:
    """Only multi-material files are counted; unreadable files give no count."""
    from batchslicer.services.gcode_stats import count_filament_changes

    single = tmp_path / "single.gcode"
    single.write_text("; total filament weight [g] : 7.4\nT0\nT1\n")
    assert read_gcode_stats(single).filament_changes is None
    assert count_filament_changes(tmp_path / "missing.gcode") is None


def test_filament_types_are_read_per_slot(tmp_path: Path) -> None:
    """The slicer's ``filament_type`` settings line gives each slot's material."""
    gcode = tmp_path / "part.gcode"
    gcode.write_text("G1 X1\n; filament used [g] = 13.78, 0.39\n; filament_type = PETG;PLA\n")

    assert read_gcode_stats(gcode).filament_types == ("PETG", "PLA")


@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        (GcodeStats(print_seconds=10_253, filament_types=("PETG",)), "PETG_2h51m"),
        (GcodeStats(print_seconds=2_700, filament_types=("PETG", "PETG"),
                    grams_per_filament=(14.2, 0.4)), "PETG_45m"),
        (GcodeStats(print_seconds=60, filament_types=("PLA", "TPU", "PETG"),
                    grams_per_filament=(3.0, 1.0, 0.0)), "PLA-TPU_1m"),
        (GcodeStats(filament_types=("PETG HF",)), "PETG-HF"),
        (GcodeStats(print_seconds=93_600), "1d2h0m"),
        (GcodeStats(), ""),
    ],
)
def test_name_details_give_the_materials_used_and_the_print_time(stats: GcodeStats, expected: str) -> None:
    """Only the slots a print uses count, each material once, made safe for a file name."""
    assert name_details(stats) == expected
