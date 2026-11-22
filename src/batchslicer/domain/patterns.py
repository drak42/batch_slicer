"""Match model paths against the patterns people type (``--exclude``, ``--slot``).

Patterns use shell wildcards (``*``, ``?``, ``[...]``) and ignore case. A
pattern without ``/`` matches any folder or file name at any depth
(``Cura-*``, ``*_lens.stl``); a pattern with ``/`` matches a path within the
folder being sliced (``kits/old``, ``*/lights/*``).
"""

from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath


def normalise(patterns: Iterable[str]) -> list[str]:
    """Return the patterns lower-cased, without surrounding ``/`` and blanks; empty ones dropped."""
    rules = (pattern.strip().strip("/").casefold() for pattern in patterns)
    return [rule for rule in rules if rule]


def path_matches(model: Path, root: Path, rule: str) -> bool:
    """Return whether ``model`` (inside ``root``) matches one normalised ``rule``."""
    try:
        relative = PurePosixPath(model.relative_to(root).as_posix().casefold())
    except ValueError:
        relative = PurePosixPath(model.name.casefold())
    if "/" in rule:
        # The model's path and each folder it is in, e.g. "kits", "kits/old", "kits/old/a.stl".
        prefixes = (PurePosixPath(*relative.parts[:depth]) for depth in range(1, len(relative.parts) + 1))
        return any(fnmatchcase(str(prefix), rule) for prefix in prefixes)
    return any(fnmatchcase(part, rule) for part in relative.parts)
