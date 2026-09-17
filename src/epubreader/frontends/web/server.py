# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The HTTP surface for :class:`WebFrontend`.

Thin by design: every route either reads the view-model or calls a frontend
operation, which in turn drives the session. The interesting endpoint is
``/resource/{key}`` — the web analogue of the Qt scheme handler. It serves book
bytes through the engine's single choke point and stamps a strict
Content-Security-Policy so book content cannot reach the network, the web
counterpart of the Qt deny-first interceptor.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ...core.exceptions import NavigationError, ResourceNotFoundError
from .frontend import WebFrontend

_STATIC = Path(__file__).parent / "static"
_MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MB — generous for an EPUB, bounds memory
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _js_string(value: str) -> str:
    """Safely encode a string as a JS literal for inline injection."""
    return json.dumps(value)


class GoToBody(BaseModel):
    key: str = ""
    fragment: str = ""
    spine_index: int | None = None


class BookmarkBody(BaseModel):
    label: str = ""


class ProgressBody(BaseModel):
    progress: float


class SettingsBody(BaseModel):
    theme: str = "obsidian"
    font_scale: float = 1.0
    allow_scripts: bool = False


class HitBody(BaseModel):
    hit: dict


def _content_security_policy(script_src: str) -> str:
    # Book content may load only same-origin subresources (its own images, CSS,
    # fonts) plus data: URIs; everything else — remote images, trackers, network
    # — is denied. Scripts are off unless the reader opts in per session.
    return (
        "default-src 'none'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        f"script-src {script_src}; "
        "base-uri 'none'; "
        "form-action 'none'"
    )


def create_app(
    frontend: WebFrontend,
    *,
    token: str | None = None,
    allowed_hosts: set[str] | None = None,
) -> FastAPI:
    """Build the app.

    ``token`` and ``allowed_hosts`` add a trust boundary for the local control
    plane; the launcher always supplies both. When neither is given (tests,
    embedding) enforcement is off, so behaviour is unchanged.
    """
    app = FastAPI(title="epubreader", docs_url=None, redoc_url=None)

    def _host_ok(request: Request) -> bool:
        if allowed_hosts is None:
            return True
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in allowed_hosts

    def _origin_ok(request: Request) -> bool:
        if allowed_hosts is None:
            return True
        origin = request.headers.get("origin")
        if not origin:
            return True  # non-CORS navigations (iframe/resource) send no Origin
        host = (urlparse(origin).hostname or "").lower()
        return host in allowed_hosts

    @app.middleware("http")
    async def _trust_boundary(request: Request, call_next):
        # Anti-DNS-rebinding: only serve requests whose Host is one we expect.
        if not _host_ok(request):
            return JSONResponse({"detail": "bad host"}, status_code=400)
        path = request.url.path
        # The control-plane API requires the per-launch capability token and,
        # for state-changing methods, a same-origin request. /resource and
        # static assets are loaded by the browser itself (no custom header
        # possible) and only ever serve the user's own book bytes.
        if path.startswith("/api/"):
            if request.method in _WRITE_METHODS and not _origin_ok(request):
                return JSONResponse({"detail": "bad origin"}, status_code=403)
            if token is not None and request.headers.get("x-api-token") != token:
                return JSONResponse({"detail": "missing or bad token"}, status_code=403)
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        html = (_STATIC / "index.html").read_text(encoding="utf-8")
        # Hand the shell its capability token (empty when enforcement is off).
        inject = f'<script>window.API_TOKEN={_js_string(token or "")}</script>'
        html = html.replace("</head>", inject + "</head>", 1)
        return HTMLResponse(html)

    @app.get("/resource/{key:path}", include_in_schema=False)
    def resource(key: str) -> Response:
        try:
            data, media = frontend.resource(key)
        except ResourceNotFoundError:
            raise HTTPException(status_code=404, detail="resource not found")
        except NavigationError:
            raise HTTPException(status_code=409, detail="no book open")
        headers = {
            "Content-Security-Policy": _content_security_policy(frontend.script_policy()),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        }
        return Response(content=data, media_type=media, headers=headers)

    @app.get("/api/state")
    def state() -> dict:
        return frontend.state()

    @app.get("/api/toc")
    def toc() -> list[dict]:
        return frontend.toc()

    @app.post("/api/upload")
    async def upload(request: Request, name: str = "book.epub") -> dict:
        # Raw-body upload streamed straight to a private temp file, so a large
        # upload is never held whole in memory. The size cap aborts mid-stream.
        new_dir, dest = frontend.prepare_upload(name)
        total = 0
        try:
            with open(dest, "wb") as fh:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > _MAX_UPLOAD_BYTES:
                        frontend.abort_upload(new_dir)
                        raise HTTPException(status_code=413, detail="file too large")
                    fh.write(chunk)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            frontend.abort_upload(new_dir)
            raise HTTPException(status_code=400, detail="upload failed")
        if total == 0:
            frontend.abort_upload(new_dir)
            raise HTTPException(status_code=400, detail="empty upload")
        try:
            return frontend.adopt_upload(new_dir, dest)
        except Exception as exc:  # noqa: BLE001 - adopt_upload already cleaned up
            raise HTTPException(status_code=400, detail=f"could not open EPUB: {exc}")

    @app.post("/api/next")
    def go_next() -> dict:
        return _guard(frontend.go_next)

    @app.post("/api/prev")
    def go_prev() -> dict:
        return _guard(frontend.go_prev)

    @app.post("/api/goto")
    def go_to(body: GoToBody) -> dict:
        return _guard(
            lambda: frontend.go_to(
                key=body.key, fragment=body.fragment, spine_index=body.spine_index
            )
        )

    @app.get("/api/search")
    def search(q: str, case: bool = False, word: bool = False) -> list[dict]:
        if not frontend.session.is_open:
            return []
        return frontend.search(q, case_sensitive=case, whole_word=word)

    @app.post("/api/search/goto")
    def search_goto(body: HitBody) -> dict:
        return _guard(lambda: frontend.go_to_hit(body.hit))

    @app.get("/api/bookmarks")
    def list_bookmarks() -> list[dict]:
        if not frontend.session.is_open:
            return []
        return frontend.bookmarks()

    @app.post("/api/bookmarks")
    def add_bookmark(body: BookmarkBody) -> dict:
        return _guard(lambda: frontend.add_bookmark(body.label))

    @app.delete("/api/bookmarks/{bookmark_id}")
    def remove_bookmark(bookmark_id: str) -> dict:
        return _guard(lambda: frontend.remove_bookmark(bookmark_id))

    @app.post("/api/bookmarks/{bookmark_id}/goto")
    def goto_bookmark(bookmark_id: str) -> dict:
        return _guard(lambda: frontend.go_to_bookmark(bookmark_id))

    @app.post("/api/progress")
    def progress(body: ProgressBody) -> JSONResponse:
        if not math.isfinite(body.progress):
            raise HTTPException(status_code=400, detail="progress must be finite")
        frontend.report_progress(body.progress)
        return JSONResponse({"ok": True})

    @app.post("/api/settings")
    def settings(body: SettingsBody) -> dict:
        return _guard(
            lambda: frontend.update_settings(
                theme=body.theme,
                font_scale=body.font_scale,
                allow_scripts=body.allow_scripts,
            )
        )

    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
    return app


def _guard(op) -> dict:  # noqa: ANN001
    """Run a session operation, turning navigation errors into 409s."""
    try:
        return op()
    except NavigationError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
