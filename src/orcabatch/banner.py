"""Generate the OrcaBatch startup banner from canonical version metadata.

This module formats display text only. It does not print, log, inspect the
terminal, or provide styling.
"""

from .version import get_version, get_version_string


def get_separator(width: int = 60) -> str:
    """Return a separator composed of ``width`` equals-sign characters."""
    return "=" * width


def get_banner() -> str:
    """Return the formatted OrcaBatch startup banner with a trailing newline."""
    current_version = get_version()
    separator = get_separator()

    return "\n".join(
        (
            separator,
            "",
            get_version_string(),
            "",
            "Print Automation Platform",
            "",
            f"Python {current_version.python_minimum}+",
            "",
            separator,
            "",
        )
    )
