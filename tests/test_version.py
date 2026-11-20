"""Tests for the BatchSlicer version service."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from batchslicer.version import (
    CURRENT_VERSION,
    Version,
    __version__,
    get_version,
    get_version_string,
)


def test_current_version_exists() -> None:
    """The module exposes the canonical version constant."""
    assert CURRENT_VERSION is not None


def test_get_version_returns_a_version() -> None:
    """The public API returns immutable version metadata."""
    assert isinstance(get_version(), Version)


def test_product_name_is_batchslicer() -> None:
    """The canonical product name is BatchSlicer."""
    assert get_version().product_name == "BatchSlicer"


def test_repository_name_is_batch_slicer() -> None:
    """The canonical repository name is batch_slicer."""
    assert get_version().repository_name == "batch_slicer"


def test_version_string_uses_the_standard_format() -> None:
    """The display string combines product name and version."""
    assert get_version_string() == f"BatchSlicer v{__version__}"


def test_version_is_immutable() -> None:
    """Version metadata cannot be changed after construction."""
    with pytest.raises(FrozenInstanceError):
        CURRENT_VERSION.version = "0.2.0"


def test_version_number_is_written_once() -> None:
    """The package build reads the version from version.py instead of repeating it."""
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in pyproject
    assert 'attr = "batchslicer.version.__version__"' in pyproject
    assert CURRENT_VERSION.version == __version__


def test_changelog_describes_the_current_version() -> None:
    """Every version has a changelog entry before it is released."""
    changelog = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")

    assert f"## [{__version__}]" in changelog
