"""The web page: what the watch folder is doing and what it has sliced.

A Starlette application with pages made on the server from Jinja2
templates; htmx (shipped in ``static/``) refreshes the queue and the results
every few seconds. Everything shown is read from files: the watched folder
and its status file (:mod:`batchslicer.services.watch_status`) and the
reports and G-code in the output folder (:mod:`batchslicer.services.results`).
The page never slices; the watcher does.

It answers only to the host names ``localhost`` and ``127.0.0.1``, so a
website cannot reach it by pointing its own name at this computer. This
first version only shows things: it accepts no uploads and changes nothing.
"""

import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from batchslicer.services.results import RunResult, find_results, get_result, inside
from batchslicer.services.thumbnails import read_preview
from batchslicer.services.watch_status import WatchStatus, read_status
from batchslicer.services.watching import candidates
from batchslicer.version import __version__

ALLOWED_HOSTS = ("localhost", "127.0.0.1")
REFRESH_SECONDS = 3
_HERE = Path(__file__).parent
_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
        b"frame-ancestors 'none'; form-action 'self'",
    ),
)


@dataclass(frozen=True, slots=True)
class WebSettings:
    """What the page shows."""

    watched: Path
    """The watched folder (where the watcher writes its status file)."""

    output: Path
    """The output folder, used until the watcher says where its output goes."""


def create_app(settings: WebSettings) -> Starlette:
    """Return the web application for ``settings``."""
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.globals.update(
        version=f"v{__version__}", refresh=REFRESH_SECONDS, preview_url=preview_url
    )
    templates.env.filters.update(when=_when, grams=_grams, url_path=_url_path)

    def output_folder(status: WatchStatus | None) -> Path:
        return Path(status.output) if status is not None and status.output else settings.output

    def queue_context() -> dict[str, object]:
        status = read_status(settings.watched)
        try:
            waiting = [path.name for path in candidates(settings.watched)]
        except OSError:
            waiting = []
        if status is not None and status.drop in waiting:
            waiting.remove(status.drop)
        return {
            "status": status,
            "waiting": waiting,
            "watched": settings.watched,
            "output": output_folder(status),
        }

    def results_context() -> dict[str, object]:
        return {"results": find_results(output_folder(read_status(settings.watched)))}

    async def index(request: Request) -> Response:
        return templates.TemplateResponse(
            request, "index.html", {**queue_context(), **results_context()}
        )

    async def queue(request: Request) -> Response:
        return templates.TemplateResponse(request, "_queue.html", queue_context())

    async def results(request: Request) -> Response:
        return templates.TemplateResponse(request, "_results.html", results_context())

    async def result(request: Request) -> Response:
        found = get_result(output_folder(read_status(settings.watched)), request.path_params["name"])
        if found is None:
            return templates.TemplateResponse(
                request, "missing.html", {"name": request.path_params["name"]}, status_code=404
            )
        return templates.TemplateResponse(request, "result.html", {"result": found})

    async def preview(request: Request) -> Response:
        """The largest preview picture in one G-code file of the output folder."""
        output = output_folder(read_status(settings.watched))
        path = inside(output, request.path_params["path"])
        if path is None or path.suffix.casefold() != ".gcode" or not path.is_file():
            return Response("Not found", status_code=404, media_type="text/plain")
        png = read_preview(path)
        if png is None:
            return Response("No preview picture", status_code=404, media_type="text/plain")
        return Response(png, media_type="image/png", headers={"cache-control": "private, max-age=86400"})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/queue", queue),
            Route("/results", results),
            Route("/results/{name:path}", result),
            Route("/preview/{path:path}", preview),
            Mount("/static", StaticFiles(directory=_HERE / "static"), name="static"),
        ],
        middleware=[
            Middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS)),
            Middleware(_SecurityHeaders),
        ],
    )


def preview_url(result: RunResult, gcode: str) -> str:
    """Return the address of a G-code file's preview picture, changing when the file does."""
    path = result.folder / gcode
    try:
        version = path.stat().st_mtime_ns
    except OSError:
        version = 0
    return f"/preview/{_url_path(result.name)}/{_url_path(gcode)}?v={version}"


class _SecurityHeaders:
    """Add headers that keep other websites from framing the page or loading foreign content."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _when(value: str | datetime) -> str:
    """Return a time as ``14:05`` today, or ``24 Nov 14:05`` on another day."""
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except ValueError:
        return str(value)
    today = datetime.fromtimestamp(time.time()).date()
    return moment.strftime("%H:%M" if moment.date() == today else "%d %b %H:%M")


def _url_path(value: str) -> str:
    """Return a path for use in a web address, with spaces and other characters escaped."""
    return urllib.parse.quote(value, safe="/")


def _grams(value: float | None) -> str:
    """Return grams of filament as ``41 g`` (``4.2 g`` under 10 g), or an empty string."""
    if value is None:
        return ""
    return f"{value:.1f} g" if value < 10 else f"{value:.0f} g"
