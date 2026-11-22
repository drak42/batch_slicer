"""Send sliced G-code to a networked printer.

After a run, the G-code of every model that sliced is uploaded to the chosen
printer. A batch keeps its folder structure on the printer, inside a folder
named like the batch folder (``Downloads-20261122-073000/kits/bracket.gcode``),
without the extra per-model folder BatchSlicer keeps locally; a single model
goes straight into the printer's G-code folder. Files already on the printer
with the same name are replaced. A print is started only when asked for and
only for a run that produced exactly one G-code file. One file failing to
upload does not stop the others. This module does not parse options or
prompt; the printer is reached through :mod:`batchslicer.infrastructure.moonraker`.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from batchslicer.domain.printers import PrinterHost
from batchslicer.infrastructure.moonraker import MoonrakerClient, MoonrakerError
from batchslicer.services.slicing import SliceOutcome


@dataclass(frozen=True, slots=True)
class Upload:
    """One G-code file and where it goes on the printer."""

    local: Path
    folder: str
    """Folder inside the printer's G-code folder, ``/``-separated; ``""`` for the top."""

    @property
    def remote_path(self) -> str:
        """Return where the file will be on the printer."""
        return str(PurePosixPath(self.folder, self.local.name)) if self.folder else self.local.name


@dataclass(frozen=True, slots=True)
class SentFile:
    """How sending one file went."""

    upload: Upload
    remote_path: str = ""
    """Where the printer stored the file (as it reports it)."""

    error: str = ""
    """Why the file was not sent; empty when it was."""

    print_started: bool = False
    print_queued: bool = False

    @property
    def success(self) -> bool:
        """Return whether the file is on the printer."""
        return not self.error


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """How sending a run's G-code to one printer went."""

    host: PrinterHost
    files: tuple[SentFile, ...]

    @property
    def sent(self) -> tuple[SentFile, ...]:
        """Return the files that reached the printer."""
        return tuple(item for item in self.files if item.success)

    @property
    def failed(self) -> tuple[SentFile, ...]:
        """Return the files that did not reach the printer."""
        return tuple(item for item in self.files if not item.success)


SendCallback = Callable[[int, int, SentFile], None]
"""Called as ``(number, total, result)`` after each file is sent or fails."""


def plan_uploads(outcomes: Sequence[SliceOutcome], base: Path) -> list[Upload]:
    """Return the uploads for the G-code of every successful outcome.

    Folders are taken from where each model's job folder sits under ``base``
    (the run's output folder), leaving out the job folder itself. When two
    files would land on the same path, those files keep their job folder.
    """
    root = base.absolute()
    uploads: list[tuple[Upload, Upload]] = []
    for outcome in outcomes:
        if not outcome.success:
            continue
        job = outcome.job_directory.absolute()
        try:
            parent = job.parent.relative_to(root)
        except ValueError:
            parent = Path()
        for gcode in outcome.gcode_files:
            short = Upload(gcode, _posix(parent))
            full = Upload(gcode, _posix(parent / job.name) if parent.parts else "")
            uploads.append((short, full))

    counts: dict[str, int] = {}
    for short, _ in uploads:
        key = short.remote_path.casefold()
        counts[key] = counts.get(key, 0) + 1
    return [full if counts[short.remote_path.casefold()] > 1 else short for short, full in uploads]


class SendingService:
    """Upload G-code files to one printer."""

    def __init__(self, client: MoonrakerClient, *, logger: logging.Logger) -> None:
        """Store the printer's client and the logger."""
        self._client = client
        self._logger = logger

    @property
    def host(self) -> PrinterHost:
        """Return the printer files are sent to."""
        return self._client.host

    def check(self) -> str:
        """Return the printer's Klipper state (``ready``, ``startup``, ...).

        Raises :class:`MoonrakerError` if the printer does not answer.
        """
        info = self._client.server_info()
        state = str(info.get("klippy_state", "unknown"))
        self._logger.info("Printer %s answers; Klipper is %s", self.host.describe(), state)
        return state

    def send(
        self,
        uploads: Sequence[Upload],
        *,
        start: bool = False,
        on_result: SendCallback | None = None,
    ) -> SendOutcome:
        """Upload every file in turn; with ``start`` and a single file, start printing it."""
        start = start and len(uploads) == 1
        results: list[SentFile] = []
        for number, upload in enumerate(uploads, start=1):
            try:
                answer = self._client.upload(upload.local, upload.folder, start=start)
                result = SentFile(
                    upload,
                    remote_path=answer.remote_path,
                    print_started=answer.print_started,
                    print_queued=answer.print_queued,
                )
                self._logger.info("Sent %s to %s as %s", upload.local, self.host.name, answer.remote_path)
            except (MoonrakerError, OSError) as error:
                result = SentFile(upload, error=str(error))
                self._logger.error("Could not send %s to %s: %s", upload.local, self.host.name, error)
            results.append(result)
            if on_result is not None:
                on_result(number, len(uploads), result)
        return SendOutcome(self.host, tuple(results))


def _posix(path: Path) -> str:
    """Return a relative folder ``/``-separated, or ``""`` for no folder."""
    return path.as_posix() if path.parts else ""
