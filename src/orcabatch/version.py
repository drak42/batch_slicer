"""
OrcaBatch

Module:
    version.py

Purpose:
    Defines the application's identity and version information.

Responsibilities:
    - Application name
    - Version number
    - Codename
    - Author information
    - Repository information

This module intentionally contains no application logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApplicationInfo:
    """
    Immutable application metadata.

    This information is displayed by the CLI, web dashboard,
    logging system, and future update mechanism.
    """

    name: str
    version: str
    codename: str
    author: str
    repository: str
    license: str


APP = ApplicationInfo(
    name="OrcaBatch",
    version="0.1.0-alpha",
    codename="Foundation",
    author="Chris Eslick",
    repository="https://github.com/<your-github-username>/batch_slicer",
    license="MIT",
)