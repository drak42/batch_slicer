"""Run ``batchslicer web``: the web page and a watch folder run together.

``batchslicer web --profile k2-pla`` serves the page on this computer only
(``http://127.0.0.1:8765``) and watches the folder in the same process, as
``batchslicer --profile k2-pla --watch`` would; Ctrl+C stops both. The page
runs in a background thread, so the watch run keeps the terminal, its
questions and its Ctrl+C handling exactly as on the command line.

The page needs the optional ``web`` extra (Starlette, Uvicorn, Jinja2); if
it is missing, this says how to add it. This module starts and stops the
page; what the page shows is :mod:`batchslicer.web.app`, and the watching is
the normal run in :mod:`batchslicer.app`.
"""

import importlib.util
import logging
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from batchslicer.core.config import find_config_file, get_config

if TYPE_CHECKING:
    from batchslicer.web.app import WebSettings

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_REQUIRED_MODULES = ("starlette", "python_multipart", "uvicorn", "jinja2")
INSTALL_HINT = (
    "The web page needs BatchSlicer's web extra. Install it with:\n"
    "  pipx install --force \"batchslicer[web]\"\n"
    "(or, without pipx: python -m pip install \"batchslicer[web]\")"
)


@dataclass(frozen=True, slots=True)
class WebOptions:
    """Options for ``batchslicer web``."""

    port: int = DEFAULT_PORT
    run_arguments: tuple[str, ...] = ()
    """The watch run's options, without --watch (it is added)."""

    input: Path | None = None
    """--input from the run options: the folder to watch."""

    config: Path | None = None
    """--config from the run options."""


class WebError(Exception):
    """Raised when the web page cannot be started."""


def missing_modules() -> list[str]:
    """Return the web extra's modules that are not installed."""
    return [name for name in _REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def run_web(
    options: WebOptions,
    run: Callable[[Sequence[str]], int],
    *,
    write: Callable[[str], None] = print,
) -> int:
    """Serve the page, run the watch with ``run(arguments)``, and stop the page when it ends.

    Returns the watch run's exit status, or 1 if the page cannot be started.
    """
    missing = missing_modules()
    if missing:
        write(f"Missing: {', '.join(missing)}. {INSTALL_HINT}")
        return 1
    try:
        settings = _settings(options)
        listener = _listen(options.port)
    except WebError as error:
        write(f"Could not start the web page: {error}")
        return 1

    import uvicorn

    from batchslicer.web.app import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), log_level="warning", access_log=False, lifespan="off")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, name="batchslicer-web", daemon=True
    )
    thread.start()
    write(f"Web page: http://{HOST}:{options.port}  (on this computer only)")
    logging.getLogger("batchslicer").info("Web page on http://%s:%d", HOST, options.port)
    try:
        return run([*options.run_arguments, "--watch"])
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


def _settings(options: WebOptions) -> "WebSettings":
    """Return the folders the page shows: the watched folder and the configured output folder."""
    from batchslicer.web.app import WebSettings

    try:
        config = get_config(find_config_file(options.config))
        watched = (options.input or config.get_path("paths", "incoming")).expanduser().absolute()
        output = config.get_path("paths", "output").expanduser().absolute()
    except (FileNotFoundError, KeyError, ValueError) as error:
        raise WebError(str(error)) from error
    return WebSettings(watched=watched, output=output)


def _listen(port: int) -> socket.socket:
    """Open the page's listening socket on this computer only, or explain why it cannot be."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        # Lets the page start again at once after a stop; on Windows the same
        # option would let two programs share the port, so it is left off there.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((HOST, port))
        listener.listen()
    except OSError as error:
        listener.close()
        raise WebError(
            f"port {port} cannot be used ({error.strerror or error}). Is the page already "
            "running? Choose another port with --port."
        ) from error
    return listener

