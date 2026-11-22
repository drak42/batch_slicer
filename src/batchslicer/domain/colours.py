"""Name filament colours and measure how alike two colours are.

Slicers and printers give colours as ``#RRGGBB`` codes. To show them to
people, each is given the name of the nearest of a few common filament
colours ("black", "light grey", "orange"...). The distance between two
colours (``redmean``, a cheap approximation of how different they look) is
used to match a project's colours to the filaments loaded in a printer.
"""

import math
import re

_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})(?:[0-9A-Fa-f]{2})?$")

_NAMES = {
    "black": (0x10, 0x10, 0x10),
    "white": (0xF5, 0xF5, 0xF5),
    "light grey": (0xB5, 0xB8, 0xBC),
    "grey": (0x80, 0x80, 0x80),
    "dark grey": (0x45, 0x45, 0x45),
    "red": (0xD0, 0x20, 0x20),
    "dark red": (0x80, 0x10, 0x18),
    "orange": (0xF2, 0x7A, 0x1A),
    "yellow": (0xF5, 0xD3, 0x1A),
    "beige": (0xD8, 0xC3, 0x9A),
    "brown": (0x7A, 0x4A, 0x25),
    "green": (0x2E, 0x9E, 0x3A),
    "dark green": (0x1E, 0x4D, 0x2B),
    "light green": (0x9C, 0xDB, 0x6E),
    "teal": (0x14, 0x8F, 0x8F),
    "light blue": (0x7C, 0xC4, 0xF0),
    "blue": (0x1E, 0x5A, 0xD6),
    "dark blue": (0x1B, 0x1F, 0x7A),
    "purple": (0x7B, 0x3F, 0xB0),
    "pink": (0xF2, 0x8C, 0xC0),
    "magenta": (0xD0, 0x1F, 0xA0),
    "silver": (0xC8, 0xCC, 0xD0),
    "gold": (0xC8, 0x9B, 0x3C),
}

RGB = tuple[int, int, int]


def parse_colour(text: str) -> RGB | None:
    """Return ``#RRGGBB`` (or ``#RRGGBBAA``, or without ``#``) as numbers, or None."""
    match = _HEX.match(text.strip())
    if match is None:
        return None
    value = match.group(1)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def colour_name(text: str) -> str:
    """Return the name of the nearest common filament colour, or ``""`` if ``text`` is no colour."""
    colour = parse_colour(text)
    if colour is None:
        return ""
    return min(_NAMES, key=lambda name: colour_distance(colour, _NAMES[name]))


def colour_distance(first: RGB, second: RGB) -> float:
    """Return how different two colours look (0 for the same; about 765 at most)."""
    mean_red = (first[0] + second[0]) / 2
    red = first[0] - second[0]
    green = first[1] - second[1]
    blue = first[2] - second[2]
    return math.sqrt(
        (2 + mean_red / 256) * red * red + 4 * green * green + (2 + (255 - mean_red) / 256) * blue * blue
    )
