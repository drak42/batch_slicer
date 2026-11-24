"""Run BatchSlicer as a Windows background service.

Task Scheduler starts this with ``pythonw.exe`` (Python without a console
window)::

    pythonw -m batchslicer.cli.service_host LOG_FILE STOP_FILE -- BATCHSLICER_OPTIONS

BatchSlicer's output is appended to ``LOG_FILE``, since a program without a
console has nowhere else to write it. When ``STOP_FILE`` appears, BatchSlicer
is interrupted as if Ctrl+C had been pressed, so slicers are stopped and a
drop being sliced stays in the watched folder; Task Scheduler's own "end
task" would kill it mid-write instead. This module only hosts a run; what is
run is decided by ``batchslicer service install`` (:mod:`batchslicer.cli.service`).
"""

import _thread
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

STOP_CHECK_SECONDS = 1.0


def main(argv: Sequence[str] | None = None) -> int:
    """Run BatchSlicer with its output in a file until it ends or a stop is requested."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 3 or arguments[2] != "--":
        print("usage: python -m batchslicer.cli.service_host LOG_FILE STOP_FILE -- OPTIONS", file=sys.stderr)
        return 2
    log_file, stop_file = Path(arguments[0]), Path(arguments[1])
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.unlink(missing_ok=True)  # a request left over from before is not for this run
    stream = log_file.open("a", encoding="utf-8", errors="replace", buffering=1)
    previous = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = stream
    finished = threading.Event()
    threading.Thread(target=watch_for_stop, args=(stop_file,), kwargs={"finished": finished}, daemon=True).start()
    from batchslicer.app import main as run_batchslicer

    try:
        return run_batchslicer(arguments[3:])
    finally:
        finished.set()
        stop_file.unlink(missing_ok=True)
        sys.stdout, sys.stderr = previous
        stream.close()


def watch_for_stop(
    stop_file: Path,
    *,
    finished: threading.Event | None = None,
    interrupt: Callable[[], None] = _thread.interrupt_main,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait until ``stop_file`` exists, then interrupt the main thread as Ctrl+C would.

    Returns without interrupting once ``finished`` is set (the run ended by itself).
    """
    while not stop_file.exists():
        if finished is not None and finished.is_set():
            return
        sleep(STOP_CHECK_SECONDS)
    interrupt()


if __name__ == "__main__":
    raise SystemExit(main())
