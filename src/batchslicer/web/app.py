"""The web page: what the watch folder is doing and what it has sliced.

A Starlette application with pages made on the server from Jinja2
templates; htmx (shipped in ``static/``) refreshes the queue and the results
every few seconds. Everything shown is read from files: the watched folder
and its status file (:mod:`batchslicer.services.watch_status`) and the
reports and G-code in the output folder (:mod:`batchslicer.services.results`).
The page never slices; the watcher does.

Uploads go into the watched folder through :mod:`batchslicer.services.uploads`;
G-code and reports can be downloaded one by one or a run at a time as a ZIP.
Paths never come from the browser unchecked: uploads only ever land in the
watched folder, and downloads only come from the output folder.

It answers only to the host names ``localhost`` and ``127.0.0.1``, so a
website cannot reach it by pointing its own name at this computer. Requests
that change something (uploads) must carry the page's own token and come
from the page itself, so another website open in the same browser cannot
send them.
"""

import secrets
import tempfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from batchslicer.services.results import (
    RunResult,
    downloadable,
    find_results,
    get_result,
    inside,
    write_zip,
)
from batchslicer.services.thumbnails import read_preview
from batchslicer.services.uploads import (
    MAX_FILES,
    MAX_UPLOAD_BYTES,
    Upload,
    UploadError,
    UploadResult,
    describe_size,
    remove_stale_uploads,
)
from batchslicer.services.watch_status import WatchStatus, read_status
from batchslicer.services.watching import candidates
from batchslicer.version import __version__

ALLOWED_HOSTS = ("localhost", "127.0.0.1")
REFRESH_SECONDS = 3
TOKEN_HEADER = "x-batchslicer-token"
_FORM_OVERHEAD_BYTES = 16 * 1024 * 1024
"""Room in a request for the form's own text around the files."""
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
    token = secrets.token_urlsafe(32)
    remove_stale_uploads(settings.watched)
    templates = Jinja2Templates(directory=_HERE / "templates")
    templates.env.globals.update(
        version=f"v{__version__}",
        refresh=REFRESH_SECONDS,
        preview_url=preview_url,
        token=token,
        max_upload_mb=MAX_UPLOAD_BYTES // 1024**2,
        max_upload=describe_size(MAX_UPLOAD_BYTES),
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
        png = await run_in_threadpool(read_preview, path)
        if png is None:
            return Response("No preview picture", status_code=404, media_type="text/plain")
        return Response(png, media_type="image/png", headers={"cache-control": "private, max-age=86400"})

    async def download(request: Request) -> Response:
        """One G-code file or report from the output folder."""
        path = inside(output_folder(read_status(settings.watched)), request.path_params["path"])
        if path is None or not downloadable(path) or not path.is_file():
            return Response("Not found", status_code=404, media_type="text/plain")
        return FileResponse(path, filename=path.name)

    async def download_zip(request: Request) -> Response:
        """A run's G-code files and reports as one ZIP file."""
        found = get_result(output_folder(read_status(settings.watched)), request.path_params["name"])
        if found is None:
            return Response("Not found", status_code=404, media_type="text/plain")
        with tempfile.NamedTemporaryFile(prefix="batchslicer-", suffix=".zip", delete=False) as stream:
            archive = Path(stream.name)
            await run_in_threadpool(write_zip, found, stream)
        return FileResponse(
            archive,
            filename=f"{Path(found.name).name}.zip",
            media_type="application/zip",
            background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    async def upload(request: Request) -> Response:
        """Models, zip files and folders from the page, into the watched folder."""
        refusal = _refusal(request, token)
        if refusal is not None:
            return refusal
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return _error("The upload did not say how large it is.", 411)
        if int(length) > MAX_UPLOAD_BYTES + _FORM_OVERHEAD_BYTES:
            return _error(f"Too large: at most {describe_size(MAX_UPLOAD_BYTES)} at a time.", 413)
        async with request.form(max_files=MAX_FILES, max_fields=MAX_FILES + 10) as form:
            names = form.getlist("path")
            files = form.getlist("file")
            if not files or len(names) != len(files):
                return _error("Nothing was uploaded.", 400)
            pairs = [
                (str(name), file) for name, file in zip(names, files, strict=True) if isinstance(file, UploadFile)
            ]
            try:
                result = await run_in_threadpool(_store, settings.watched, pairs)
            except UploadError as error:
                return _error(str(error), 413)
            except OSError as error:
                return _error(f"Could not store the upload: {error}", 500)
        return JSONResponse({"added": result.added, "skipped": result.skipped})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/queue", queue),
            Route("/results", results),
            Route("/results/{name:path}", result),
            Route("/preview/{path:path}", preview),
            Route("/download/{path:path}", download),
            Route("/zip/{name:path}", download_zip),
            Route("/upload", upload, methods=["POST"]),
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


def _store(watched: Path, files: list[tuple[str, UploadFile]]) -> UploadResult:
    """Write uploaded files into the watched folder, all or nothing."""
    pending = Upload(watched)
    try:
        for name, file in files:
            pending.add(name, file.file)
    except BaseException:
        pending.discard()
        raise
    return pending.finish()


def _refusal(request: Request, token: str) -> Response | None:
    """Return why a request that changes something is refused, or None if it may go ahead.

    It must carry the page's token, and if the browser says where it came
    from, that must be this page.
    """
    if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, ""), token):
        return _error("This request did not come from the BatchSlicer page. Reload the page.", 403)
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
        return _error("This request came from another website.", 403)
    if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
        return _error("This request came from another website.", 403)
    return None


def _error(message: str, status_code: int) -> Response:
    """Return a refusal the page can show."""
    return JSONResponse({"error": message}, status_code=status_code)


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
