"""Tests for the BatchSlicer version service."""

from dataclasses import FrozenInstanceError

import pytest

from batchslicer.version import CURRENT_VERSION, Version, get_version, get_version_string


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
    assert get_version_string() == "BatchSlicer v0.1.0"


def test_version_is_immutable() -> None:
    """Version metadata cannot be changed after construction."""
    with pytest.raises(FrozenInstanceError):
        CURRENT_VERSION.version = "0.2.0"
