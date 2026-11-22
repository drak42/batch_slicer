"""Store profiles in a YAML file.

Profiles are kept in one human-readable YAML file, by default
``~/.local/share/batchslicer/profiles.yaml``. The file is written atomically
(to a temporary file that then replaces it), so an interrupted save never
leaves it half-written. This module only reads and writes profiles; it does
not decide when to save them or check that their choices still exist.
"""

import tempfile
from pathlib import Path
from typing import Any

import yaml

from batchslicer.domain.options import MAX_COPIES, MAX_JOBS, orient_mode, slot_rule
from batchslicer.domain.profiles import (
    RUN_FIELDS,
    SETTING_FIELDS,
    TARGET_FIELDS,
    Profile,
    Target,
    is_valid_name,
)


class ProfileError(Exception):
    """Raised when profiles cannot be read, found or saved."""


class ProfileStore:
    """Read and write the profiles in one YAML file."""

    def __init__(self, path: Path) -> None:
        """Use the profiles file at ``path``; it need not exist yet."""
        self._path = path

    @property
    def path(self) -> Path:
        """Return the profiles file's path."""
        return self._path

    def load(self) -> dict[str, Profile]:
        """Return every saved profile by name; an absent file means none."""
        if not self._path.exists():
            return {}
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ProfileError(f"Cannot read profiles from {self._path}: {error}") from error
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ProfileError(f"Profiles file is not a mapping of names: {self._path}")
        return {
            str(name): self._profile(str(name), values)
            for name, values in data.items()
        }

    def get(self, name: str) -> Profile:
        """Return the named profile, ignoring case.

        Raises :class:`ProfileError` naming the saved profiles if there is none.
        """
        profiles = self.load()
        for saved_name, profile in profiles.items():
            if saved_name.casefold() == name.strip().casefold():
                return profile
        available = ", ".join(sorted(profiles)) or "none saved yet"
        raise ProfileError(f"No profile named '{name}' (saved profiles: {available}).")

    def save(self, profile: Profile) -> None:
        """Save ``profile``, replacing any profile with the same name."""
        if not is_valid_name(profile.name):
            raise ProfileError(
                f"Invalid profile name '{profile.name}': use letters, digits, spaces, "
                "dots, dashes and underscores (up to 64 characters)."
            )
        profiles = self.load()
        for existing in list(profiles):
            if existing.casefold() == profile.name.casefold():
                del profiles[existing]
        profiles[profile.name] = profile
        self._write(profiles)

    def delete(self, name: str) -> Profile:
        """Delete the named profile and return it."""
        profile = self.get(name)
        profiles = self.load()
        del profiles[profile.name]
        self._write(profiles)
        return profile

    def _profile(self, name: str, values: Any) -> Profile:
        """Return the Profile stored under ``name``.

        A profile with one target stores its choices directly; a profile with
        several stores them as a ``targets`` list. ``input`` and ``output`` are
        shared by every target.
        """
        if not isinstance(values, dict):
            raise ProfileError(f"Profile '{name}' in {self._path} is not a mapping.")
        allowed = {*TARGET_FIELDS, *RUN_FIELDS, *SETTING_FIELDS, "targets"}
        unknown = set(values) - allowed
        if unknown:
            raise ProfileError(
                f"Profile '{name}' in {self._path} has unknown settings: "
                + ", ".join(sorted(str(key) for key in unknown))
            )

        if "targets" in values:
            if any(key in values for key in TARGET_FIELDS):
                raise ProfileError(
                    f"Profile '{name}' in {self._path} sets both 'targets' and "
                    "slicer/printer/filament/process; put those inside each target."
                )
            entries = values["targets"]
            if not isinstance(entries, list) or not entries:
                raise ProfileError(f"Profile '{name}' in {self._path}: 'targets' must be a list.")
            targets = tuple(self._target(name, entry) for entry in entries)
        else:
            targets = (self._target(name, values),)

        paths: dict[str, Any] = {
            key: Path(str(values[key])).expanduser()
            for key in RUN_FIELDS
            if values.get(key) not in (None, "")
        }
        return Profile(name=name, targets=targets, **paths, **self._settings(name, values))

    def _settings(self, name: str, values: dict[Any, Any]) -> dict[str, Any]:
        """Return the slicing settings stored for profile ``name``, checked."""
        settings: dict[str, Any] = {}
        where = f"Profile '{name}' in {self._path}"
        if values.get("orient") is not None:
            try:
                settings["orient"] = orient_mode(str(values["orient"]))
            except ValueError as error:
                raise ProfileError(f"{where}: {error}.") from error
        if values.get("allow_newer_files") is not None:
            if not isinstance(values["allow_newer_files"], bool):
                raise ProfileError(f"{where}: allow_newer_files must be true or false.")
            settings["allow_newer_files"] = values["allow_newer_files"]
        for key in ("thumbnails", "plates", "loaded_filaments"):
            if values.get(key) is not None:
                if not isinstance(values[key], bool):
                    raise ProfileError(f"{where}: {key} must be true or false.")
                settings[key] = values[key]
        if values.get("slots") is not None:
            slots = values["slots"]
            if not isinstance(slots, dict):
                raise ProfileError(f"{where}: slots must map patterns to slots, such as '*_lens.stl': 2.")
            try:
                settings["slots"] = tuple(slot_rule(f"{pattern}={slot}") for pattern, slot in slots.items())
            except ValueError as error:
                raise ProfileError(f"{where}: slots: {error}.") from error
        if values.get("copies") is not None:
            copies = values["copies"]
            if isinstance(copies, bool) or not isinstance(copies, int) or not 1 <= copies <= MAX_COPIES:
                raise ProfileError(f"{where}: copies must be a whole number from 1 to {MAX_COPIES}.")
            settings["copies"] = copies
        if values.get("jobs") is not None:
            jobs = values["jobs"]
            if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= MAX_JOBS:
                raise ProfileError(f"{where}: jobs must be a whole number from 1 to {MAX_JOBS}.")
            settings["jobs"] = jobs
        if values.get("exclude") is not None:
            exclude = values["exclude"]
            if isinstance(exclude, str):
                exclude = [exclude]
            if not isinstance(exclude, list) or not all(isinstance(item, str) for item in exclude):
                raise ProfileError(f"{where}: exclude must be a pattern or a list of patterns.")
            settings["exclude"] = tuple(exclude)
        return settings

    def _target(self, name: str, values: Any) -> Target:
        """Return one target from its stored settings."""
        if not isinstance(values, dict):
            raise ProfileError(f"Profile '{name}' in {self._path} has a target that is not a mapping.")
        unknown = set(values) - set(TARGET_FIELDS) - set(RUN_FIELDS) - set(SETTING_FIELDS)
        if unknown:
            raise ProfileError(
                f"Profile '{name}' in {self._path} has unknown target settings: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        filament = values.get("filament")
        more: tuple[str, ...] = ()
        if isinstance(filament, list):
            names = [str(item) for item in filament if item not in (None, "")]
            if not names:
                raise ProfileError(f"Profile '{name}' in {self._path}: filament is an empty list.")
            filament, more = names[0], tuple(names[1:])
        return Target(
            **{
                key: str(filament if key == "filament" else values[key])
                for key in TARGET_FIELDS
                if values.get(key) not in (None, "", [])
            },
            more_filaments=more,
        )

    @staticmethod
    def _stored(profile: Profile) -> dict[str, Any]:
        """Return the settings written for ``profile``."""
        def choices(target: Target) -> dict[str, Any]:
            stored: dict[str, Any] = {
                key: getattr(target, key) for key in TARGET_FIELDS if getattr(target, key)
            }
            if target.more_filaments:
                stored["filament"] = list(target.filaments)
            return stored

        stored: dict[str, Any] = (
            {"targets": [choices(target) for target in profile.targets]}
            if profile.is_multi
            else choices(profile.targets[0])
        )
        for key in RUN_FIELDS:
            value = getattr(profile, key)
            if value is not None:
                stored[key] = str(value)
        for key in SETTING_FIELDS:
            value = getattr(profile, key)
            if value is not None and key == "slots":
                stored[key] = {pattern: int(slot) if slot.isdigit() else slot for pattern, slot in value}
            elif value is not None:
                stored[key] = list(value) if isinstance(value, tuple) else value
        return stored

    def _write(self, profiles: dict[str, Profile]) -> None:
        """Write all profiles, replacing the file atomically."""
        data = {
            name: self._stored(profile)
            for name, profile in sorted(profiles.items(), key=lambda item: item[0].casefold())
        }
        text = (
            "# BatchSlicer profiles: saved choices for runs. Edit freely. A profile sets\n"
            "# slicer, printer, filament and process (or a 'targets' list of them, to\n"
            "# slice for several printers), plus input and output, and optionally\n"
            "# orient (off/retry/always), allow_newer_files (true/false), jobs,\n"
            "# exclude (a list of patterns), thumbnails and plates (true/false), copies\n"
            "# (a number, for a single model), loaded_filaments (true/false), slots\n"
            "# (pattern: filament slot, for STL files) and, per\n"
            "# printer, send (a printer's address or configured name). filament may\n"
            "# be a list, one per slot of a multi-material printer (CFS, AMS).\n"
            + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=".profiles-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(text)
            Path(temporary.name).replace(self._path)
        except OSError as error:
            raise ProfileError(f"Cannot save profiles to {self._path}: {error}") from error
