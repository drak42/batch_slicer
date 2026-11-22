"""Read and resolve presets from a Bambu-family slicer data directory.

Creality Print and OrcaSlicer store the user's own presets as JSON files under
``user/<user id>/<kind>/`` in the data directory. Shipped presets are JSON files
under ``<vendor>/<kind>/`` in a system folder (see :mod:`batchslicer.backends.profiles`).
Most presets only store differences from the preset they ``inherits`` from, and
the slicer's command line cannot use them as saved, so this module:

- lists the printers the user has set up, and the filament and process presets
  compatible with a chosen printer, the way the slicer's own menus do (shipped
  filaments are limited to those the user has made visible in the slicer);
- writes complete, self-contained copies of a selection that the slicer's
  command line accepts.

It does not modify the slicer's data directory, read account credentials, or
evaluate ``compatible_printers_condition`` expressions.
"""

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from batchslicer.core.logging import get_logger
from batchslicer.domain.presets import Preset, PresetKind, PresetSelection

_DEFAULT_USER_DIRECTORY = "default"


class PresetError(Exception):
    """Raised when presets cannot be read or resolved."""


class PresetLibrary:
    """Provide the presets found in one slicer data directory."""

    def __init__(
        self,
        data_directory: Path,
        app_config_name: str,
        *,
        system_directory: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Index the presets in ``data_directory``.

        ``app_config_name`` is the slicer's settings file in that directory
        (for example ``Creality.conf``), which records the signed-in user, the
        printers the user has added and the filaments they made visible.
        ``system_directory`` holds the shipped presets; it defaults to the data
        directory's ``system`` folder.
        """
        self._root = data_directory
        self._logger = logger or get_logger()
        self._app_config = self._read_app_config(data_directory / app_config_name)
        self._user_directory = self._find_user_directory()
        self._visible_filaments = self._read_visible_filaments()
        system_root = system_directory or data_directory / "system"
        self._system: dict[PresetKind, dict[str, tuple[Path, dict[str, Any]]]] = {}
        self._user: dict[PresetKind, dict[str, tuple[Path, dict[str, Any]]]] = {}
        for kind in PresetKind:
            self._system[kind] = self._index(system_root.glob(f"*/{kind.value}/**/*.json"))
            self._user[kind] = (
                self._index(sorted((self._user_directory / kind.value).glob("*.json")))
                if self._user_directory is not None
                else {}
            )

    def printers(self) -> list[Preset]:
        """Return the user's saved printers, then the shipped printers the user has added."""
        printers = [
            self._preset(PresetKind.PRINTER, name, is_user=True)
            for name in sorted(self._user[PresetKind.PRINTER])
        ]
        seen = {printer.name for printer in printers}
        for name in self._added_printer_names():
            if name in seen or name not in self._system[PresetKind.PRINTER]:
                continue
            seen.add(name)
            printers.append(self._preset(PresetKind.PRINTER, name, is_user=False))
        return printers

    def filaments_for(self, printer: Preset) -> list[Preset]:
        """Return filament presets compatible with ``printer``, the user's own first.

        Shipped filaments are limited to those visible in the slicer, when the
        slicer records that list.
        """
        filaments = self._compatible(PresetKind.FILAMENT, printer)
        if not self._visible_filaments:
            return filaments
        return [
            preset
            for preset in filaments
            if preset.is_user or preset.name in self._visible_filaments
        ]

    def processes_for(self, printer: Preset) -> list[Preset]:
        """Return process presets compatible with ``printer``, the user's own first."""
        return self._compatible(PresetKind.PROCESS, printer)

    def resolve(self, preset: Preset) -> dict[str, Any]:
        """Return ``preset`` merged with every preset it inherits from."""
        chain: list[dict[str, Any]] = []
        data = self._data(preset.kind, preset.name)
        visited: set[str] = set()
        while True:
            chain.append(data)
            parent = data.get("inherits")
            if not parent:
                break
            if parent in visited:
                raise PresetError(f"Preset inheritance loops at '{parent}'.")
            visited.add(parent)
            data = self._data(preset.kind, parent)

        merged: dict[str, Any] = {}
        for layer in reversed(chain):
            merged.update(layer)
        merged.pop("inherits", None)
        merged["name"] = preset.name
        merged["type"] = preset.kind.value
        return merged

    def write_resolved(
        self,
        selection: PresetSelection,
        directory: Path,
        *,
        link_user_printer: bool = True,
    ) -> tuple[list[Path], list[Path]]:
        """Write complete copies of ``selection`` into ``directory`` for the slicer CLI.

        Returns ``(settings_files, filament_files)`` for ``--load-settings`` and
        ``--load-filaments``. ``link_user_printer`` keeps a user's printer linked
        to the shipped printer it is based on (see :meth:`_printer_for_cli`).
        """
        directory.mkdir(parents=True, exist_ok=True)
        printer = self._printer_for_cli(selection.printer, link_user_printer=link_user_printer)
        process = self.resolve(selection.process)
        process["from"] = "User"
        process["print_settings_id"] = selection.process.name
        filament = self.resolve(selection.filament)
        filament["from"] = "User"
        filament["filament_settings_id"] = [selection.filament.name]

        paths = []
        for kind, data in (
            (PresetKind.PRINTER, printer),
            (PresetKind.PROCESS, process),
            (PresetKind.FILAMENT, filament),
        ):
            path = directory / f"{kind.value}.json"
            path.write_text(json.dumps(data, indent=4), encoding="utf-8")
            paths.append(path)
        return [paths[0], paths[1]], [paths[2]]

    def _printer_for_cli(self, printer: Preset, *, link_user_printer: bool = True) -> dict[str, Any]:
        """Return a resolved printer the CLI accepts and matches compatibility against.

        The CLI matches a shipped printer by its own name. Before OrcaSlicer 2.5
        it matches a user's printer by the shipped printer it inherits from, so
        that link is kept; from 2.5 the CLI looks that printer up itself and
        refuses the file if it cannot, so the (already complete) file goes
        without it.
        """
        data = self.resolve(printer)
        data["printer_settings_id"] = printer.name
        if printer.is_user:
            data["from"] = "User"
            if link_user_printer:
                data["inherits"] = self._compatibility_name(printer)
        else:
            data["from"] = "system"
        return data

    def _compatible(self, kind: PresetKind, printer: Preset) -> list[Preset]:
        """Return presets of ``kind`` usable with ``printer``."""
        printer_name = self._compatibility_name(printer)
        presets = [
            self._preset(kind, name, is_user=True) for name in sorted(self._user[kind])
        ]
        presets.extend(
            self._preset(kind, name, is_user=False)
            for name, (_, data) in sorted(self._system[kind].items())
            if data.get("instantiation") == "true"
        )
        return [
            preset
            for preset in presets
            if self._is_compatible(preset, printer_name)
        ]

    def _is_compatible(self, preset: Preset, printer_name: str) -> bool:
        """Return whether ``preset`` lists ``printer_name``, or lists no printers at all."""
        compatible = self._inherited_value(preset.kind, preset.name, "compatible_printers")
        return not compatible or printer_name in compatible

    def _compatibility_name(self, printer: Preset) -> str:
        """Return the shipped printer name that compatibility lists refer to."""
        if not printer.is_user:
            return printer.name
        parent = self._data(PresetKind.PRINTER, printer.name).get("inherits")
        if not parent:
            return printer.name
        return str(parent)

    def _inherited_value(self, kind: PresetKind, name: str, key: str) -> Any:
        """Return ``key`` from the named preset or the nearest preset it inherits from."""
        visited: set[str] = set()
        current: str | None = name
        while current and current not in visited:
            visited.add(current)
            data = self._data(kind, current)
            if key in data:
                return data[key]
            current = data.get("inherits")
        return None

    def _data(self, kind: PresetKind, name: str) -> dict[str, Any]:
        """Return the raw data of a user or shipped preset by name."""
        entry = self._user[kind].get(name) or self._system[kind].get(name)
        if entry is None:
            raise PresetError(f"{kind.label} preset not found: {name}")
        return entry[1]

    def _preset(self, kind: PresetKind, name: str, *, is_user: bool) -> Preset:
        """Return the Preset for an indexed preset."""
        index = self._user if is_user else self._system
        return Preset(name=name, kind=kind, path=index[kind][name][0], is_user=is_user)

    def _added_printer_names(self) -> list[str]:
        """Return the shipped printers the user has added in the slicer, in its order."""
        names: list[str] = []
        for entry in self._app_config.get("orca_presets", []):
            if isinstance(entry, dict) and isinstance(entry.get("machine"), str):
                names.append(entry["machine"])
        current = self._app_config.get("presets", {}).get("machine")
        if isinstance(current, str) and current not in names:
            names.append(current)
        return names

    def _read_visible_filaments(self) -> frozenset[str]:
        """Return the shipped filaments the user has made visible in the slicer."""
        names = self._app_config.get("filaments")
        if not isinstance(names, list):
            return frozenset()
        return frozenset(name for name in names if isinstance(name, str))

    def _find_user_directory(self) -> Path | None:
        """Return the signed-in user's preset folder, else the default one."""
        cloud = self._app_config.get("cloud")
        user_id = cloud.get("user_id") if isinstance(cloud, dict) else None
        for name in (user_id, _DEFAULT_USER_DIRECTORY):
            if isinstance(name, str) and name and (self._root / "user" / name).is_dir():
                return self._root / "user" / name
        return None

    def _index(self, paths: Iterable[Path]) -> dict[str, tuple[Path, dict[str, Any]]]:
        """Return named presets from ``paths``; files that are not presets are skipped."""
        index: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                self._logger.warning("Skipping unreadable preset %s: %s", path, error)
                continue
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                index.setdefault(data["name"], (path, data))
        return index

    @staticmethod
    def _read_app_config(path: Path) -> dict[str, Any]:
        """Return the slicer's settings file, which may have trailing text after the JSON."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise PresetError(f"Cannot read slicer settings file: {path}") from error
        end = text.rfind("}")
        try:
            data = json.loads(text[: end + 1])
        except ValueError as error:
            raise PresetError(f"Slicer settings file is not valid JSON: {path}") from error
        if not isinstance(data, dict):
            raise PresetError(f"Slicer settings file is not a JSON object: {path}")
        return data
