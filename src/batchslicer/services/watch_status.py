"""Tell others what a watch folder run is doing, through a small status file.

A watching BatchSlicer writes ``.batchslicer-status.json`` into the watched
folder: whether it is waiting or slicing, which drop and which model of how
many, where the G-code goes, and the drops it finished most recently. The
web page reads it to show progress; anything else may too. The file is
hidden, so the watcher never takes it for a drop, and it is replaced in one
step, so a reader never sees half of it. This module only writes and reads
the file; it does not watch or slice.
"""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

STATUS_FILE = ".batchslicer-status.json"
RECENT_DROPS = 50
"""How many finished drops the status file remembers."""

WATCHING = "watching"
SLICING = "slicing"
STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class FinishedDrop:
    """A drop the watcher has handled."""

    name: str
    success: bool
    finished: str
    """When it finished, as an ISO 8601 local time."""

    moved_to: str = ""
    """Where it was moved, relative to the watched folder (``sliced/cube.stl``); empty if it could not be."""


@dataclass(frozen=True, slots=True)
class WatchStatus:
    """What a watch run is doing."""

    state: str
    """``watching`` (waiting for drops), ``slicing`` or ``stopped``."""

    folder: str
    output: str
    pid: int
    started: str
    updated: str
    drop: str = ""
    """The drop being sliced, while slicing."""

    model: str = ""
    """The model being sliced, relative to the drop, when known."""

    number: int = 0
    count: int = 0
    """The model being sliced is ``number`` of ``count`` (0 when not known)."""

    recent: tuple[FinishedDrop, ...] = field(default_factory=tuple)
    """The drops finished most recently, newest first."""


class StatusWriter:
    """Keep a watched folder's status file up to date.

    Writing is best effort: a status file that cannot be written must never
    stop the watcher, so errors are passed to ``on_error`` and otherwise ignored.
    """

    def __init__(
        self,
        folder: Path,
        output: Path,
        *,
        clock: Callable[[], datetime] = datetime.now,
        on_error: Callable[[OSError], None] | None = None,
    ) -> None:
        """Write the status of watching ``folder`` with output to ``output``."""
        self.path = folder / STATUS_FILE
        self._clock = clock
        self._on_error = on_error
        now = self._now()
        self._status = WatchStatus(
            state=WATCHING,
            folder=str(folder),
            output=str(output),
            pid=os.getpid(),
            started=now,
            updated=now,
        )

    @property
    def status(self) -> WatchStatus:
        """Return the status as last written."""
        return self._status

    def watching(self) -> None:
        """Record that the watcher is waiting for drops."""
        self._write(state=WATCHING, drop="", model="", number=0, count=0)

    def slicing(self, drop: str) -> None:
        """Record that ``drop`` is being sliced."""
        self._write(state=SLICING, drop=drop, model="", number=0, count=0)

    def progress(self, number: int, count: int, model: str) -> None:
        """Record that model ``number`` of ``count`` of the current drop is being sliced."""
        self._write(model=model, number=number, count=count)

    def finished(self, drop: str, *, success: bool, moved_to: str = "") -> None:
        """Record that ``drop`` was handled, and that the watcher waits again."""
        done = FinishedDrop(name=drop, success=success, finished=self._now(), moved_to=moved_to)
        recent = (done, *self._status.recent)[:RECENT_DROPS]
        self._write(state=WATCHING, drop="", model="", number=0, count=0, recent=recent)

    def stopped(self) -> None:
        """Record that the watcher has stopped."""
        self._write(state=STOPPED, drop="", model="", number=0, count=0)

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _write(self, **changes: Any) -> None:
        self._status = replace(self._status, updated=self._now(), **changes)
        try:
            _replace_json(self.path, asdict(self._status))
        except OSError as error:
            if self._on_error is not None:
                self._on_error(error)


def read_status(folder: Path) -> WatchStatus | None:
    """Return the status written in ``folder``, or None if there is none or it cannot be read."""
    try:
        data = json.loads((folder / STATUS_FILE).read_text(encoding="utf-8"))
        recent = tuple(FinishedDrop(**drop) for drop in data.pop("recent", []))
        return WatchStatus(**data, recent=recent)
    except (OSError, ValueError, TypeError):
        return None


def _replace_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` as JSON through a temporary file in the same folder, then swap it in."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f"{path.name}-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
