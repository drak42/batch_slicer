"""Tests for giving loose models their own filament slot (--slot)."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from batchslicer.backends.orca import OrcaBackend
from batchslicer.domain.options import SliceOptions, is_loaded_slot, slot_for, slot_rule, slot_value
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection
from batchslicer.services.slicing import SlicingService
from conftest import write_config
from test_slicing_service import NOW, _backend


def test_slot_rules_are_read() -> None:
    """PATTERN=SLOT takes numbers, CFS slots and external; anything else is explained."""
    assert slot_rule("*_lens.stl=2") == ("*_lens.stl", "2")
    assert slot_rule(" kits/a=b/*.stl = 1c ") == ("kits/a=b/*.stl", "1C")
    assert slot_value("EXTERNAL") == "external"
    assert slot_value("07") == "7"
    for bad in ("0", "17", "5A", "1E", "red"):
        with pytest.raises(ValueError, match="not a filament slot"):
            slot_value(bad)
    with pytest.raises(ValueError, match="PATTERN=SLOT"):
        slot_rule("*_lens.stl")
    assert is_loaded_slot("1B") and is_loaded_slot("external") and not is_loaded_slot("2")


def test_the_first_matching_rule_gives_the_slot(tmp_path: Path) -> None:
    """Names match at any depth, paths from the folder; no match means slot 1."""
    rules = (("lights/*", "3"), ("*_lens.stl", "2"), ("*", "1B"))
    root = tmp_path / "kit"
    assert slot_for(root / "lights" / "a_lens.stl", root, rules) == "3"
    assert slot_for(root / "body" / "A_LENS.STL", root, rules) == "2"
    assert slot_for(root / "body.stl", root, rules) == "1B"
    assert slot_for(root / "body.stl", root, rules[:2]) == "1"


def test_filament_ids_are_passed_to_the_slicer(tmp_path: Path) -> None:
    """--load-filament-ids gives each input its slot."""
    config = write_config(
        tmp_path, {"orca": {"executable": tmp_path / "Orca Slicer", "datadir": tmp_path / "Orca Data"}}
    )
    backend = OrcaBackend(config=config, logger=Mock())

    command = backend.build_slice_command([tmp_path / "a.stl", tmp_path / "b.stl"], tmp_path, filament_ids=(1, 2))

    assert command[command.index("--load-filament-ids") + 1] == "1,2"
    assert "--load-filament-ids" not in backend.build_slice_command(tmp_path / "a.stl", tmp_path)


def _service(tmp_path: Path, slots: tuple[tuple[str, str], ...], *, filaments: int = 2, matcher: Mock | None = None,
             plates: bool = True) -> tuple[SlicingService, Mock, list[Path]]:
    backend = _backend()
    library = Mock()
    files = [tmp_path / f"filament-{n}.json" for n in range(1, filaments + 1)]
    library.write_resolved.return_value = ([tmp_path / "machine.json"], files)
    options = SliceOptions(plates=plates, slots=slots)
    service = SlicingService(backend, presets=library, logger=Mock(), clock=lambda: NOW, options=options,
                             matcher=matcher)
    return service, backend, files


def _selection() -> PresetSelection:
    def preset(name: str, kind: PresetKind) -> Preset:
        return Preset(name, kind, Path(name), is_user=False)
    return PresetSelection(preset("K2", PresetKind.PRINTER), preset("PLA", PresetKind.FILAMENT),
                           preset("Fine", PresetKind.PROCESS))


def _kit(tmp_path: Path) -> tuple[Path, list[Path]]:
    root = tmp_path / "in"
    models = [root / "kit" / name for name in ("arm.stl", "body.stl", "lens.stl")]
    for model in models:
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("solid")
    return root, models


def test_a_kit_on_one_plate_gets_each_parts_slot(tmp_path: Path) -> None:
    """Slots are numbered in order, slot 1 first; each model gets its slot among them."""
    service, backend, files = _service(tmp_path, (("lens.stl", "3"), ("arm*", "2")), filaments=3)
    root, models = _kit(tmp_path)

    batch = service.slice_batch(models, root, tmp_path / "out", _selection())

    assert batch.outcomes[0].success
    kwargs = backend.slice.call_args.kwargs
    assert kwargs["load_filaments"] == files
    assert kwargs["filament_ids"] == [2, 1, 3]


def test_one_slot_for_everything_needs_no_ids(tmp_path: Path) -> None:
    """A single model, or models all in one slot, just get that filament."""
    service, backend, files = _service(tmp_path, (("*", "2"),), plates=False)
    root, models = _kit(tmp_path)

    service.slice(models[0], tmp_path / "out", _selection())

    assert backend.slice.call_args.kwargs["load_filaments"] == [files[1]]


def test_slots_that_cannot_be_filled_fail_with_the_reason(tmp_path: Path) -> None:
    """A number beyond the filaments given, or a loaded slot without the printer's filaments."""
    root, models = _kit(tmp_path)
    service, backend, _ = _service(tmp_path, (("lens.stl", "3"),), plates=False)
    outcome = service.slice(models[2], tmp_path / "out", _selection())
    assert outcome.message == "--slot 3 needs at least 3 filaments; give --filament 3 times (slot 1 first)."
    backend.slice.assert_not_called()

    service, _, _ = _service(tmp_path, (("lens.stl", "1B"),), plates=False)
    assert "needs --loaded-filaments" in service.slice(models[2], tmp_path / "out", _selection()).message

    matcher = Mock()
    matcher.file_for_slot.return_value = None
    service, _, _ = _service(tmp_path, (("lens.stl", "4D"),), plates=False, matcher=matcher)
    assert "no filament loaded there" in service.slice(models[2], tmp_path / "out", _selection()).message


def test_loaded_slots_use_the_printers_filaments(tmp_path: Path) -> None:
    """A CFS slot or the external spool comes from the matcher's files, after the numbered slots."""
    matcher = Mock()
    matcher.file_for_slot.side_effect = lambda slot, job: tmp_path / f"loaded-{slot}.json"
    matcher.files_for.return_value = None
    service, backend, files = _service(tmp_path, (("lens.stl", "external"), ("arm*", "1C")), matcher=matcher)
    root, models = _kit(tmp_path)

    service.slice_batch(models, root, tmp_path / "out", _selection())

    kwargs = backend.slice.call_args.kwargs
    assert kwargs["load_filaments"] == [files[0], tmp_path / "loaded-1C.json", tmp_path / "loaded-external.json"]
    assert kwargs["filament_ids"] == [2, 1, 3]


def test_3mf_projects_keep_their_own_slots(tmp_path: Path) -> None:
    """--slot does not apply to 3MF files."""
    import zipfile

    project = tmp_path / "in" / "bumper.3mf"
    project.parent.mkdir(parents=True)
    with zipfile.ZipFile(project, "w") as archive:
        archive.writestr("Metadata/project_settings.config", json.dumps({"filament_colour": ["#000000"]}))
    service, backend, files = _service(tmp_path, (("*", "2"),), plates=False)

    service.slice(project, tmp_path / "out", _selection())

    assert backend.slice.call_args.kwargs["load_filaments"] == files
