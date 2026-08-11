"""Provide the single source of truth for OrcaBatch version information.

This module exposes immutable application metadata. It does not perform I/O,
read packaging metadata, or format console output beyond the public version
string.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Version:
    """Describe immutable OrcaBatch product and runtime version metadata."""

    product_name: str
    repository_name: str
    version: str
    python_minimum: str
    copyright: str
    license: str


CURRENT_VERSION = Version(
    product_name="OrcaBatch",
    repository_name="batch_slicer",
    version="0.1.0",
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
