"""Create a minimal slicer settings folder for testing against a real slicer.

The real-slicer tests normally use the settings folder a slicer creates when a
person opens it and adds printers. On a CI machine nobody has done that, so
this script creates the smallest folder that works: the slicer's built-in
presets plus a settings file recording one added printer and the filaments
made visible. It never contains personal data.

Usage:
    python scripts/make_test_slicer_data.py SLICER EXECUTABLE TARGET

SLICER is ``orca``, ``creality_print`` or ``bambu_studio``; EXECUTABLE is the slicer's AppImage;
TARGET is the folder to create (it must not exist yet).
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PRINTER = "Creality K2 Plus 0.4 nozzle"
"""A printer OrcaSlicer and Creality Print ship presets for."""

_BAMBU_MODEL = "Creality K1 Max"
"""The closest printer Bambu Studio ships (it has no K2), recorded as an added model."""

_VISIBLE_FILAMENTS = {
    "orca": ["Generic PLA @System", "Generic PETG @System"],
    "creality_print": [
        "Generic PLA @Creality K2 Plus 0.4 nozzle",
        "Generic PETG @Creality K2 Plus 0.4 nozzle",
    ],
    "bambu_studio": ["Generic PLA @Creality", "Generic PETG @Creality"],
}
_SETTINGS_FILE = {
    "orca": "OrcaSlicer.conf",
    "creality_print": "Creality.conf",
    "bambu_studio": "BambuStudio.conf",
}


def main(arguments: list[str]) -> int:
    """Create the folder described by ``arguments`` and return an exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slicer", choices=sorted(_SETTINGS_FILE))
    parser.add_argument("executable", type=Path)
    parser.add_argument("target", type=Path)
    options = parser.parse_args(arguments)

    target: Path = options.target
    if target.exists():
        parser.error(f"{target} already exists")
    (target / "user" / "default").mkdir(parents=True)
    settings: dict[str, object] = {
        "presets": {"machine": PRINTER},
        "orca_presets": [{"machine": PRINTER}],
        "filaments": _VISIBLE_FILAMENTS[options.slicer],
    }
    if options.slicer == "bambu_studio":
        # Bambu Studio records added printer models and nozzle sizes instead.
        settings = {
            "presets": {"machine": f"{_BAMBU_MODEL} 0.4 nozzle"},
            "models": [{"model": _BAMBU_MODEL, "nozzle_diameter": "0.4", "vendor": "Creality"}],
            "filaments": _VISIBLE_FILAMENTS[options.slicer],
        }
    (target / _SETTINGS_FILE[options.slicer]).write_text(json.dumps(settings, indent=2))

    if options.slicer == "orca":
        # OrcaSlicer 2.4+ keeps built-in presets as packed <vendor>.opc files; BatchSlicer
        # only needs the file names and reads the presets from the AppImage itself.
        (target / "system").mkdir()
        for vendor in ("Creality", "OrcaFilamentLibrary"):
            (target / "system" / f"{vendor}.opc").write_bytes(b"")
    else:
        _copy_bundled_presets(options.executable.resolve(), target / "system", "Creality")
    print(f"Created {options.slicer} test settings in {target}")
    return 0


def _copy_bundled_presets(executable: Path, system: Path, vendor: str) -> None:
    """Copy a vendor's built-in presets out of the AppImage, as the slicer does on first run."""
    with tempfile.TemporaryDirectory() as scratch:
        subprocess.run(
            [str(executable), "--appimage-extract", f"resources/profiles/{vendor}*"],
            cwd=scratch,
            check=True,
            capture_output=True,
            timeout=600,
        )
        profiles = Path(scratch) / "squashfs-root" / "resources" / "profiles"
        if not (profiles / vendor).is_dir():
            raise SystemExit(f"{executable} has no built-in presets for {vendor}")
        system.mkdir(parents=True)
        shutil.copytree(profiles / vendor, system / vendor)
        if (profiles / f"{vendor}.json").is_file():
            shutil.copy2(profiles / f"{vendor}.json", system / f"{vendor}.json")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
