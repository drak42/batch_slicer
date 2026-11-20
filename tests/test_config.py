"""Tests for the BatchSlicer configuration service."""

from pathlib import Path

import pytest

from batchslicer.core.config import Config, get_config


def test_configuration_file_loads_successfully(tmp_path: Path) -> None:
    """A valid configuration file is loaded and cached."""
    config = Config(_write_config(tmp_path))

    config.load()

    assert config.get("paths", "incoming") == "incoming"


def test_load_raises_for_a_missing_configuration_file(tmp_path: Path) -> None:
    """Missing configuration files are reported explicitly."""
    with pytest.raises(FileNotFoundError):
        Config(tmp_path / "missing.yaml").load()


def test_load_raises_for_invalid_yaml(tmp_path: Path) -> None:
    """Invalid YAML is converted into a configuration error."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("orca: [")

    with pytest.raises(ValueError):
        Config(config_path).load()


def test_get_raises_for_a_missing_section(tmp_path: Path) -> None:
    """Missing sections raise KeyError."""
    config = Config(_write_config(tmp_path))

    with pytest.raises(KeyError):
        config.get("missing", "key")


def test_get_raises_for_a_missing_key(tmp_path: Path) -> None:
    """Missing keys raise KeyError."""
    config = Config(_write_config(tmp_path))

    with pytest.raises(KeyError):
        config.get("orca", "missing")


def test_has_reports_existing_and_missing_values(tmp_path: Path) -> None:
    """Presence checks distinguish existing and missing configuration values."""
    config = Config(_write_config(tmp_path))

    assert config.has("paths", "incoming")
    assert not config.has("paths", "missing")
    assert not config.has("missing", "key")


def test_get_returns_the_configured_value(tmp_path: Path) -> None:
    """Configuration values are returned without defaults or transformation."""
    config = Config(_write_config(tmp_path))

    assert config.get("paths", "output") == "output"


def test_validate_succeeds_for_existing_orca_paths(tmp_path: Path) -> None:
    """Validation accepts existing executable and data directory paths."""
    executable = tmp_path / "orca"
    datadir = tmp_path / "orca-data"
    executable.touch()
    datadir.mkdir()
    config = Config(_write_config(tmp_path, executable=executable, datadir=datadir))

    config.validate()


def test_validate_raises_for_missing_orca_paths(tmp_path: Path) -> None:
    """Validation rejects missing configured Orca paths."""
    config = Config(
        _write_config(
            tmp_path,
            executable=tmp_path / "missing-orca",
            datadir=tmp_path / "missing-data",
        )
    )

    with pytest.raises(FileNotFoundError):
        config.validate()


def test_get_config_returns_the_same_instance() -> None:
    """The public accessor returns one cached Config instance."""
    get_config.cache_clear()

    first_config = get_config()
    second_config = get_config()

    assert first_config is second_config
    get_config.cache_clear()


def _write_config(
    tmp_path: Path,
    *,
    executable: Path | None = None,
    datadir: Path | None = None,
) -> Path:
    """Write a minimal configuration file for a test case."""
    config_path = tmp_path / "config.yaml"
    executable_value = executable or tmp_path / "orca"
    datadir_value = datadir or tmp_path / "orca-data"
    config_path.write_text(
        "\n".join(
            (
                "orca:",
                f'  executable: "{executable_value}"',
                f'  datadir: "{datadir_value}"',
                "paths:",
                '  incoming: "incoming"',
                '  output: "output"',
                '  logs: "logs"',
                '  data: "data"',
                "",
            )
        )
    )
    return config_path
