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

from batchslicer.domain.profiles import CHOICE_FIELDS, Profile, is_valid_name


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
        """Return the Profile stored under ``name``."""
        if not isinstance(values, dict):
            raise ProfileError(f"Profile '{name}' in {self._path} is not a mapping.")
        unknown = set(values) - set(CHOICE_FIELDS)
        if unknown:
            raise ProfileError(
                f"Profile '{name}' in {self._path} has unknown settings: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        choices: dict[str, Any] = {}
        for key in CHOICE_FIELDS:
            value = values.get(key)
            if value in (None, ""):
                continue
            text = str(value)
            choices[key] = Path(text).expanduser() if key in ("input", "output") else text
        return Profile(name=name, **choices)

    def _write(self, profiles: dict[str, Profile]) -> None:
        """Write all profiles, replacing the file atomically."""
        data = {
            name: {
                key: str(getattr(profile, key))
                for key in CHOICE_FIELDS
                if getattr(profile, key) is not None
            }
            for name, profile in sorted(profiles.items(), key=lambda item: item[0].casefold())
        }
        text = (
            "# BatchSlicer profiles: saved choices for runs. Edit freely; each profile\n"
            "# may set slicer, printer, filament, process, input and output.\n"
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
