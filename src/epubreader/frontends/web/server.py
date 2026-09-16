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

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ...core.exceptions import NavigationError, ResourceNotFoundError
from .frontend import WebFrontend

_STATIC = Path(__file__).parent / "static"


class GoToBody(BaseModel):
    key: str = ""
    fragment: str = ""
    spine_index: int | None = None


class OpenBody(BaseModel):
    path: str


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


def create_app(frontend: WebFrontend) -> FastAPI:
    app = FastAPI(title="epubreader", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

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

    @app.post("/api/open")
    def open_book(body: OpenBody) -> dict:
        try:
            return frontend.open_path(body.path)
        except Exception as exc:  # noqa: BLE001 - report open failures as 400
            raise HTTPException(status_code=400, detail=str(exc))

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
