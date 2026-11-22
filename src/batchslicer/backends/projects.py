"""Read what a 3MF project says about its filaments.

A project saved by OrcaSlicer, Bambu Studio or Creality Print lists its
filaments (one per slot of a multi-material printer) in
``Metadata/project_settings.config``, with their colours and materials. Parts,
or painted areas of parts, use those slots by number. The slicer must be given
at least as many filaments as the project lists: with fewer, it keeps the
project's own filaments for the rest (often presets for another printer,
which can make slicing fail). This module only reads the project; it does
not change it.
"""

import json
import zipfile
from pathlib import Path

from batchslicer.domain.filaments import ProjectFilament

_SETTINGS = "Metadata/project_settings.config"
_MAX_SETTINGS_BYTES = 8 * 1024 * 1024


def project_filaments(path: Path) -> tuple[ProjectFilament, ...]:
    """Return the filament slots a 3MF project lists, or ``()`` if it lists none.

    A file that is not a 3MF project, cannot be read, or was not saved by a
    slicer that lists filaments gives ``()``.
    """
    if path.suffix.casefold() != ".3mf":
        return ()
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(_SETTINGS)
            if info.file_size > _MAX_SETTINGS_BYTES:
                return ()
            settings = json.loads(archive.read(info).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, UnicodeDecodeError):
        return ()
    if not isinstance(settings, dict):
        return ()
    colours = _texts(settings.get("filament_colour"))
    materials = _texts(settings.get("filament_type"))
    names = _texts(settings.get("filament_settings_id"))
    count = max(len(colours), len(names))
    return tuple(
        ProjectFilament(
            colour=colours[index] if index < len(colours) else "",
            material=materials[index] if index < len(materials) else "",
            name=names[index] if index < len(names) else "",
        )
        for index in range(count)
    )


def _texts(value: object) -> list[str]:
    """Return a project setting as a list of texts (a single text becomes one item)."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
