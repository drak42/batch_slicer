"""Tests for the BatchSlicer configuration service."""

from pathlib import Path

import pytest

from batchslicer.core.config import Config, find_config_file, get_config
from conftest import set_home


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


def test_get_config_returns_the_same_instance(tmp_path: Path) -> None:
    """The public accessor returns one cached Config instance per file."""
    get_config.cache_clear()
    path = _write_config(tmp_path)

    first_config = get_config(path)
    second_config = get_config(path)

    assert first_config is second_config
    assert first_config.path == path
    get_config.cache_clear()


def test_relative_paths_are_relative_to_the_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative paths do not depend on the folder BatchSlicer is run from."""
    config = Config(_write_config(tmp_path / "settings"))
    monkeypatch.chdir(tmp_path)

    assert config.get_path("paths", "output") == tmp_path / "settings" / "output"


def test_home_folder_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A leading ~ in a path means the home folder."""
    set_home(monkeypatch, tmp_path / "home")
    config = Config(_write_config(tmp_path, datadir="~/.config/OrcaSlicer"))

    assert config.get_path("orca", "datadir") == tmp_path / "home" / ".config" / "OrcaSlicer"


def test_missing_paths_use_standard_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a paths section, standard per-user locations are used."""
    home = tmp_path / "home"
    set_home(monkeypatch, home)
    for variable in ("XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    path = tmp_path / "config.yaml"
    path.write_text('orca:\n  executable: "/opt/orca"\n  datadir: "/data"\n')
    config = Config(path)

    assert config.get_path("paths", "incoming") == home / "BatchSlicer" / "incoming"
    assert config.get_path("paths", "output") == home / "BatchSlicer" / "output"
    assert config.get_path("paths", "logs") == home / ".local" / "state" / "batchslicer"
    assert config.get_path("paths", "data") == home / ".cache" / "batchslicer"


def test_empty_path_setting_uses_its_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty paths value means 'use the default'; XDG variables are honoured."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = tmp_path / "config.yaml"
    path.write_text('paths:\n  logs: ""\n')

    assert Config(path).get_path("paths", "logs") == tmp_path / "state" / "batchslicer"


def test_empty_slicer_path_is_an_error(tmp_path: Path) -> None:
    """Slicer paths have no default, so an empty one is reported."""
    path = tmp_path / "config.yaml"
    path.write_text('orca:\n  datadir: ""\n')

    with pytest.raises(ValueError, match="orca.datadir must not be empty"):
        Config(path).get_path("orca", "datadir")


def test_find_config_prefers_explicit_then_environment(tmp_path: Path) -> None:
    """--config wins, then BATCHSLICER_CONFIG; both are used even if missing."""
    explicit = tmp_path / "explicit.yaml"
    from_environment = tmp_path / "environment.yaml"
    environ = {"BATCHSLICER_CONFIG": str(from_environment)}

    assert find_config_file(explicit, environ=environ) == explicit
    assert find_config_file(environ=environ) == from_environment


def test_find_config_uses_project_then_user_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without overrides, ./config/config.yaml wins over the per-user file."""
    monkeypatch.chdir(tmp_path)
    environ = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    user = tmp_path / "xdg" / "batchslicer" / "config.yaml"
    user.parent.mkdir(parents=True)
    user.write_text("{}")

    assert find_config_file(environ=environ) == user

    project = tmp_path / "config" / "config.yaml"
    project.parent.mkdir()
    project.write_text("{}")
    assert find_config_file(environ=environ) == Path("config/config.yaml")


def test_find_config_explains_where_it_looked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no configuration anywhere, the error lists the places and how to fix it."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError) as raised:
        find_config_file(environ={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})

    message = str(raised.value)
    assert str(tmp_path / "config" / "config.yaml") in message
    assert str(tmp_path / "xdg" / "batchslicer" / "config.yaml") in message
    assert "batchslicer setup" in message


def _write_config(
    tmp_path: Path,
    *,
    executable: Path | str | None = None,
    datadir: Path | str | None = None,
) -> Path:
    """Write a minimal configuration file for a test case."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    executable_value = executable or tmp_path / "orca"
    datadir_value = datadir or tmp_path / "orca-data"
    config_path.write_text(
        "\n".join(
            (
                "orca:",
                f'  executable: "{Path(str(executable_value)).as_posix()}"',
                f'  datadir: "{Path(str(datadir_value)).as_posix()}"',
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


@pytest.mark.usefixtures("windows")
def test_windows_standard_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, settings and profiles are in %APPDATA%, logs and caches in %LOCALAPPDATA%."""
    from batchslicer.core.locations import default_paths, user_config_file

    environ = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    set_home(monkeypatch, tmp_path / "home")

    assert user_config_file(environ) == tmp_path / "Roaming" / "BatchSlicer" / "config.yaml"
    paths = default_paths(environ)
    assert paths["profiles"] == tmp_path / "Roaming" / "BatchSlicer" / "profiles.yaml"
    assert paths["logs"] == tmp_path / "Local" / "BatchSlicer" / "logs"
    assert paths["data"] == tmp_path / "Local" / "BatchSlicer" / "cache"
    assert paths["incoming"] == tmp_path / "home" / "BatchSlicer" / "incoming"
    assert default_paths({"XDG_CACHE_HOME": str(tmp_path / "xdg")})["data"] == tmp_path / "xdg" / "batchslicer"
    assert user_config_file({}) == tmp_path / "home" / "AppData" / "Roaming" / "BatchSlicer" / "config.yaml"


def test_windows_paths_in_double_quotes_are_explained(tmp_path: Path) -> None:
    """A backslash path in double quotes is a YAML escape error; the message says how to write it."""
    path = tmp_path / "config.yaml"
    path.write_text('orca:\n  executable: "C:\\Program Files\\OrcaSlicer\\orca-slicer.exe"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="forward slashes"):
        Config(path).load()
