"""Tests for the BatchSlicer banner service."""

from batchslicer.banner import get_banner, get_separator
from batchslicer.version import get_version, get_version_string


def test_get_separator_returns_requested_width() -> None:
    """Separators use the requested number of equals signs."""
    assert get_separator(12) == "=" * 12


def test_default_separator_is_sixty_characters() -> None:
    """The default separator has the banner width."""
    assert get_separator() == "=" * 60


def test_get_banner_returns_a_string() -> None:
    """The banner service returns text."""
    assert isinstance(get_banner(), str)


def test_banner_contains_canonical_version_information() -> None:
    """The banner includes product, version, and Python requirements."""
    banner = get_banner()
    current_version = get_version()

    assert current_version.product_name in banner
    assert current_version.version in banner
    assert f"Python {current_version.python_minimum}+" in banner
    assert "Print Automation Platform" in banner


def test_banner_ends_with_a_newline() -> None:
    """The banner is ready for direct startup display."""
    assert get_banner().endswith("\n")


def test_banner_includes_the_version_string_once() -> None:
    """The formatted version is not duplicated in the banner."""
    assert get_banner().count(get_version_string()) == 1
