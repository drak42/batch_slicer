"""Shared test helpers."""

from pathlib import Path

import yaml

from batchslicer.core.config import Config


def write_config(directory: Path, sections: dict[str, dict[str, object]]) -> Config:
    """Write ``sections`` as a configuration file in ``directory`` and return it loaded.

    Path values are written as strings, so relative paths are relative to
    ``directory``, exactly as for a real configuration file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    data = {
        section: {key: str(value) for key, value in values.items()}
        for section, values in sections.items()
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = Config(path)
    config.load()
    return config
