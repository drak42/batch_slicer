"""Tests for reading OrcaSlicer's packed .opc preset files."""

import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from batchslicer.backends.opc import read_opc, unpack
from batchslicer.backends.presets import PresetError

# Setting types (OrcaSlicer's ConfigOptionType).
V = 0x4000
FLOAT, INT, STRING, PERCENT, FLOAT_OR_PERCENT, POINT, POINT3, BOOL, ENUM = 1, 2, 3, 4, 5, 6, 7, 8, 9


class _Writer:
    """Write cereal binary-archive values the way OrcaSlicer does."""

    def __init__(self) -> None:
        self.data = bytearray()

    def pack(self, fmt: str, *values: object) -> "_Writer":
        self.data += struct.pack("<" + fmt, *values)
        return self

    def size(self, value: int) -> "_Writer":
        return self.pack("Q", value)

    def string(self, value: str) -> "_Writer":
        encoded = value.encode("utf-8")
        self.size(len(encoded))
        self.data += encoded
        return self

    def strings(self, values: list[str]) -> "_Writer":
        self.size(len(values))
        for value in values:
            self.string(value)
        return self


SETTINGS: list[tuple[str, int]] = [
    ("layer_height", FLOAT),
    ("wall_loops", INT),
    ("machine_start_gcode", STRING),
    ("sparse_infill_density", PERCENT),
    ("initial_layer_line_width", FLOAT_OR_PERCENT),
    ("bed_mesh_max", POINT),
    ("some_point3", POINT3),
    ("enable_arc_fitting", BOOL),
    ("brim_type", ENUM),
    ("nozzle_diameter", FLOAT | V),
    ("nozzle_temperature", INT | V),
    ("compatible_printers", STRING | V),
    ("retract_before_wipe", PERCENT | V),
    ("bridge_acceleration", FLOAT_OR_PERCENT | V),
    ("printable_area", POINT | V),
    ("activate_chamber_temp_control", BOOL | V),
    ("extruder_type", ENUM | V),
    ("some_points_groups", 10 | V),
    ("some_ints_groups", 11 | V),
]
ENUMS = ["", "auto_brim", "DirectDrive"]


def _write_value(writer: _Writer, kind: int) -> None:
    """Write a sample value of ``kind`` (see EXPECTED for what it reads as)."""
    if kind == FLOAT:
        writer.pack("d", 0.2)
    elif kind == INT:
        writer.pack("i", 3)
    elif kind == STRING:
        writer.string("G28 ; home\n")
    elif kind == PERCENT:
        writer.pack("d", 15.0)
    elif kind == FLOAT_OR_PERCENT:
        writer.pack("d?", 120.0, True)
    elif kind == POINT:
        writer.pack("dd", 99999.0, 99999.0)
    elif kind == POINT3:
        writer.pack("ddd", 1.0, 2.5, 3.0)
    elif kind == BOOL:
        writer.pack("B", 1)
    elif kind == ENUM:
        writer.pack("IH", 1, 1)
    elif kind == FLOAT | V:
        writer.size(2).pack("dd", 0.4, float("nan"))
    elif kind == INT | V:
        writer.size(2).pack("ii", 220, 2**31 - 1)
    elif kind == STRING | V:
        writer.strings(["K2 Plus", "K2 Pro"])
    elif kind == PERCENT | V:
        writer.size(1).pack("d", 80.0)
    elif kind == FLOAT_OR_PERCENT | V:
        writer.size(2).pack("d?d?", 5000.0, False, 50.0, True)
    elif kind == POINT | V:
        writer.size(2).pack("dddd", 0.0, 0.0, 350.0, 0.0)
    elif kind == BOOL | V:
        writer.size(3)
        writer.data += bytes([0, 1, 255])
    elif kind == ENUM | V:
        writer.pack("IH", 2, 2).pack("Hi", 0, 7)
    elif kind == 10 | V:
        writer.size(1).size(2).pack("dddd", 0.0, 0.0, 1.0, 1.0)
    elif kind == 11 | V:
        writer.size(2).size(2).pack("ii", 1, 2).size(1).pack("i", 3)


EXPECTED = {
    "layer_height": "0.2",
    "wall_loops": "3",
    "machine_start_gcode": "G28 ; home\n",
    "sparse_infill_density": "15%",
    "initial_layer_line_width": "120%",
    "bed_mesh_max": "99999,99999",
    "some_point3": "1,2.5,3",
    "enable_arc_fitting": "1",
    "brim_type": "auto_brim",
    "nozzle_diameter": ["0.4", "nil"],
    "nozzle_temperature": ["220", "nil"],
    "compatible_printers": ["K2 Plus", "K2 Pro"],
    "retract_before_wipe": ["80%"],
    "bridge_acceleration": ["5000", "50%"],
    "printable_area": ["0x0", "350x0"],
    "activate_chamber_temp_control": ["0", "1", "nil"],
    "extruder_type": ["DirectDrive", "7"],
    "some_points_groups": ["0x0,1x1"],
    "some_ints_groups": ["1,2", "3"],
}


def _preset(writer: _Writer, name: str, sub_path: str, settings: list[int], *, inherits: str = "",
            renamed_from: tuple[str, ...] = ()) -> None:
    """Write one preset entry with the settings at the given dictionary indexes."""
    writer.string(name).string(sub_path)
    writer.pack("I", len(settings))
    for index in settings:
        writer.pack("H", index)
        _write_value(writer, SETTINGS[index][1])
    writer.string(inherits).strings([])
    for value in ("", "true", "GP004", "GFL99"):  # description, instantiation, setting_id, filament_id
        writer.string(value)
    writer.strings(list(renamed_from))


def make_opc(path: Path, *, vendor: str = "Acme", version: int = 2, damage: bool = False) -> Path:
    """Write a small but complete .opc file for ``vendor``."""
    body = _Writer().pack("I", 2).string(vendor).string("2.3.2.89")
    body.strings([key for key, _ in SETTINGS])
    body.size(len(SETTINGS)).pack(f"{len(SETTINGS)}H", *(kind for _, kind in SETTINGS))
    body.strings(ENUMS)
    # One vendor profile with one printer model.
    body.size(1).string(vendor)
    for value in (vendor, vendor, "2.3.2", "", ""):
        body.string(value)
    body.size(1).string("A1").string("Acme One").string("acme_1").pack("B", 0).string("Acme")
    body.strings(["0.4"]).strings(["Acme PLA"]).strings([])
    for _ in range(9):
        body.string("")
    body.strings(["Acme PLA"]).strings([])
    # Processes, filaments, machines.
    body.pack("I", 1)
    _preset(body, "0.20mm Standard @Acme", "process/0.20mm Standard @Acme.json", list(range(len(SETTINGS))))
    body.pack("I", 1)
    _preset(body, "Acme PLA", "filament/Acme PLA.json", [3], inherits="fdm_filament_pla",
            renamed_from=("Old PLA", 'Odd; "name"'))
    body.pack("I", 1)
    _preset(body, "Acme One 0.4 nozzle", "machine/Acme One 0.4 nozzle.json", [0, 1],
            renamed_from=("Acme 1",))
    body.pack("Q", 0)
    data = bytes(body.data)
    crc = zlib.crc32(data) ^ (1 if damage else 0)
    path.write_bytes(struct.pack("<IIQI", 0x4F52435A, version, len(data), crc) + data)
    return path


def test_every_setting_type_reads_as_orcaslicer_text(tmp_path: Path) -> None:
    """Each setting type is read and written the way OrcaSlicer's JSON presets state it."""
    vendor = read_opc(make_opc(tmp_path / "Acme.opc"))

    assert (vendor.name, vendor.version) == ("Acme", "2.3.2.89")
    assert [preset.kind for preset in vendor.presets] == ["process", "filament", "machine"]
    assert vendor.presets[0].settings == EXPECTED
    filament = vendor.presets[1]
    assert (filament.name, filament.inherits, filament.instantiation) == ("Acme PLA", "fdm_filament_pla", "true")
    assert filament.renamed_from == ("Old PLA", 'Odd; "name"')


def test_unpack_writes_the_json_preset_layout(tmp_path: Path) -> None:
    """Presets are written as <vendor>/<kind>/<name>.json, as older slicers shipped them."""
    vendor = read_opc(make_opc(tmp_path / "Acme.opc"))

    folder = unpack(vendor, tmp_path / "out")

    machine = json.loads((folder / "machine" / "Acme One 0.4 nozzle.json").read_text(encoding="utf-8"))
    assert machine == {
        "type": "machine",
        "name": "Acme One 0.4 nozzle",
        "from": "system",
        "instantiation": "true",
        "setting_id": "GP004",
        "filament_id": "GFL99",
        "renamed_from": "Acme 1",
        "layer_height": "0.2",
        "wall_loops": "3",
    }
    filament = json.loads((folder / "filament" / "Acme PLA.json").read_text(encoding="utf-8"))
    assert filament["inherits"] == "fdm_filament_pla"
    assert filament["renamed_from"] == '"Old PLA";"Odd; \\"name\\""'


@pytest.mark.parametrize(
    ("options", "message"),
    [({"version": 3}, "format 3"), ({"damage": True}, "damaged")],
)
def test_unreadable_files_are_explained(tmp_path: Path, options: dict[str, object], message: str) -> None:
    """A newer format or a damaged file stops with a clear reason."""
    path = make_opc(tmp_path / "Acme.opc", **options)  # type: ignore[arg-type]

    with pytest.raises(PresetError, match=message):
        read_opc(path)


def test_other_files_are_refused(tmp_path: Path) -> None:
    """A file that is not a preset file is refused, including an empty one."""
    for content in (b"", b"PK\x03\x04" + bytes(40)):
        path = tmp_path / "Other.opc"
        path.write_bytes(content)
        with pytest.raises(PresetError, match="not an OrcaSlicer preset file"):
            read_opc(path)


def test_truncated_file_is_refused(tmp_path: Path) -> None:
    """A body that ends early is reported, not read past."""
    path = make_opc(tmp_path / "Acme.opc")
    data = path.read_bytes()
    body = data[20:-40]
    path.write_bytes(struct.pack("<IIQI", 0x4F52435A, 2, len(body), zlib.crc32(body)) + body)

    with pytest.raises(PresetError, match="Cannot read the presets"):
        read_opc(path)


def test_preset_paths_cannot_leave_the_vendor_folder(tmp_path: Path) -> None:
    """A preset whose stored path climbs out of its folder is refused."""
    from batchslicer.backends.opc import OpcPreset, OpcVendor

    vendor = OpcVendor("Acme", "1", (OpcPreset("machine", "Bad", "../../evil.json", {}),))

    with pytest.raises(PresetError, match="unexpected file path"):
        unpack(vendor, tmp_path / "out")
    assert not (tmp_path / "evil.json").exists()


@pytest.mark.skipif(
    not os.environ.get("BATCHSLICER_TEST_ORCA_DATADIR"),
    reason="Set BATCHSLICER_TEST_ORCA_DATADIR to read a real OrcaSlicer's .opc files.",
)
def test_real_opc_files_read_completely() -> None:
    """Every .opc file in a real OrcaSlicer settings folder reads to its end."""
    system = Path(os.environ["BATCHSLICER_TEST_ORCA_DATADIR"]).expanduser() / "system"
    files = sorted(system.glob("*.opc"))
    if not files:
        pytest.skip(f"No .opc files in {system}.")
    for path in files:
        vendor = read_opc(path)
        assert vendor.name == path.stem
        assert vendor.presets
