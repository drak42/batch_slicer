"""Provide the single source of truth for BatchSlicer version information.

This module exposes immutable application metadata. ``__version__`` is the
only place the version number is written: the package build reads it from
here (see ``pyproject.toml``). It does not perform I/O, read packaging
metadata, or format console output beyond the public version string.
"""

from dataclasses import dataclass

__version__ = "0.9.0"


@dataclass(frozen=True)
class Version:
    """Describe immutable BatchSlicer product and runtime version metadata."""

    product_name: str
    repository_name: str
    version: str
    python_minimum: str
    copyright: str
    license: str


CURRENT_VERSION = Version(
    product_name="BatchSlicer",
    repository_name="batch_slicer",
    version=__version__,
    python_minimum="3.12",
    copyright="Copyright (c) 2026 Christopher Eslick",
    license="MIT",
)


def get_version() -> Version:
    """Return the current immutable application version metadata."""
    return CURRENT_VERSION


def get_version_string() -> str:
    """Return the current version in the standard display format."""
    current_version = get_version()
    return f"{current_version.product_name} v{current_version.version}"
