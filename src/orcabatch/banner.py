"""
OrcaBatch

Module:
    banner.py

Purpose:
    Generates the OrcaBatch application banner.

Responsibilities:
    - Display application identity
    - Display version information
    - Provide a consistent startup banner

This module intentionally performs no console output.
It only returns formatted strings.
"""

from .version import APP


def create_banner() -> str:
    """
    Create the OrcaBatch startup banner.

    Returns:
        A formatted banner string.
    """

    return (
        "=" * 60
        + "\n"
        + f"{APP.name}\n"
        + "Print Automation Platform\n\n"
        + f"Version  : {APP.version}\n"
        + f"Release  : {APP.codename}\n"
        + f"Author   : {APP.author}\n"
        + "=" * 60
    )