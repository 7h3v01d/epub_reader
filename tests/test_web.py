# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Web frontend tests — the routes exercised end to end with a real session.

No browser is involved, but every HTTP path the shell uses is covered here, so
the seam between the engine and an HTTP transport is verified in the sandbox.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="web frontend deps not installed")
pytest.importorskip("httpx", reason="TestClient needs httpx")

from fastapi.testclient import TestClient  # noqa: E402

from epubreader.core.exceptions import ResourceNotFoundError  # noqa: E402
from epubreader.frontend.base import ReaderFrontend  # noqa: E402
from epubreader.frontends.web.frontend import WebFrontend  # noqa: E402
from epubreader.frontends.web.server import create_app  # noqa: E402
from epubreader.session.session import ReaderSession  # noqa: E402
from epubreader.session.storage import MemoryProgressStore  # noqa: E402


@pytest.fixture()
def web(epub3_path):
    frontend = WebFrontend(ReaderSession(MemoryProgressStore()))
    frontend.open_path(str(epub3_path))
    return frontend, TestClient(create_app(frontend))


def test_web_frontend_is_a_readerfrontend(web):
    frontend, _ = web
    # The payoff: the web UI satisfies the same contract as the Qt window.
    assert isinstance(frontend, ReaderFrontend)


def test_state_reports_open_book(web):
    _, client = web
    state = client.get("/api/state").json()
    assert state["is_open"] is True
    assert state["section"]["key"] == "OEBPS/ch1.xhtml"
    assert state["metadata"]["title"]


def test_resource_serves_themed_html_with_csp(web):
    _, client = web
    r = client.get("/resource/OEBPS/ch1.xhtml")
    assert r.status_code == 200
    assert b"epubreader injected theme" in r.content        # theme injected
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp                      # deny-first
    assert "script-src 'none'" in csp                       # scripts off by default


def test_resource_unknown_key_is_404(web):
    _, client = web
    assert client.get("/resource/OEBPS/nope.xhtml").status_code == 404


def test_resource_traversal_key_is_rejected(web):
    # read_resource only serves archive members, so a traversal key resolves to
    # nothing — the deny-first guarantee, checked at the choke point directly.
    frontend, _ = web
    with pytest.raises(ResourceNotFoundError):
        frontend.resource("../../etc/passwd")


def test_web_never_enables_book_scripts(web):
    # Security invariant (CRITICAL fix): because book content shares an origin
    # with the reader shell, the web frontend must never allow book scripts —
    # not even when the setting is toggled on.
    frontend, client = web
    assert frontend.script_policy() == "'none'"
    client.post(
        "/api/settings", json={"theme": "obsidian", "font_scale": 1.0, "allow_scripts": True}
    )
    csp = client.get("/resource/OEBPS/ch1.xhtml").headers["content-security-policy"]
    assert "script-src 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_next_and_prev(web):
    _, client = web
    assert client.post("/api/next").json()["section"]["spine_index"] == 1
    assert client.post("/api/prev").json()["section"]["spine_index"] == 0


def test_goto_by_key(web):
    _, client = web
    state = client.post("/api/goto", json={"key": "OEBPS/ch2.xhtml"}).json()
    assert state["section"]["spine_index"] == 1


def test_toc_is_nested(web):
    _, client = web
    toc = client.get("/api/toc").json()
    assert toc[0]["label"] == "Chapter One"
    assert toc[0]["children"][0]["label"] == "Chapter Two"


def test_search_returns_hits(web):
    _, client = web
    hits = client.get("/api/search", params={"q": "Chapter"}).json()
    assert len(hits) == 2
    assert client.get("/api/search", params={"q": "chapter", "case": True}).json() == []


def test_search_goto_sets_one_shot_highlight(web):
    _, client = web
    hit = client.get("/api/search", params={"q": "World"}).json()[0]
    state = client.post("/api/search/goto", json={"hit": hit}).json()
    assert state["section"]["spine_index"] == 1
    assert state["section"]["highlight"] == "World"
    # One-shot: a subsequent plain state read no longer carries the highlight.
    assert client.get("/api/state").json()["section"]["highlight"] == ""


def test_bookmarks_add_list_remove(web):
    _, client = web
    added = client.post("/api/bookmarks", json={"label": "spot"}).json()["bookmarks"]
    assert len(added) == 1
    bid = added[0]["id"]
    assert client.get("/api/bookmarks").json()[0]["label"] == "spot"
    remaining = client.delete(f"/api/bookmarks/{bid}").json()["bookmarks"]
    assert remaining == []


def test_bookmark_goto_restores_section(web):
    _, client = web
    client.post("/api/next")                       # to spine 1
    bid = client.post("/api/bookmarks", json={"label": ""}).json()["bookmarks"][0]["id"]
    client.post("/api/prev")                        # back to spine 0
    state = client.post(f"/api/bookmarks/{bid}/goto").json()
    assert state["section"]["spine_index"] == 1


def test_progress_endpoint_ok(web):
    _, client = web
    assert client.post("/api/progress", json={"progress": 0.5}).json() == {"ok": True}


def test_progress_endpoint_rejects_non_finite(web):
    _, client = web
    # A raw client can send the literal `NaN` (Python's JSON parser accepts it);
    # the API must reject it rather than persisting a poisoned float.
    r = client.post(
        "/api/progress",
        content=b'{"progress": NaN}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400   # rejected at the API boundary, not persisted


def test_upload_size_limit_enforced_while_streaming(empty_client, monkeypatch):
    from epubreader.frontends.web import server

    monkeypatch.setattr(server, "_MAX_UPLOAD_BYTES", 100)
    _, client = empty_client
    assert client.post("/api/upload", content=b"x" * 500).status_code == 413


# ---- control-plane trust boundary ----------------------------------------- #
@pytest.fixture()
def secured(epub3_path):
    frontend = WebFrontend(ReaderSession(MemoryProgressStore()))
    frontend.open_path(str(epub3_path))
    app = create_app(frontend, token="secret-token", allowed_hosts={"127.0.0.1", "localhost"})
    client = TestClient(app, base_url="http://127.0.0.1")
    return frontend, client


def test_api_requires_token(secured):
    _, client = secured
    assert client.get("/api/state").status_code == 403                     # no token
    assert client.get("/api/state", headers={"x-api-token": "wrong"}).status_code == 403
    assert client.get("/api/state", headers={"x-api-token": "secret-token"}).status_code == 200


def test_index_injects_token(secured):
    _, client = secured
    body = client.get("/").text
    assert "window.API_TOKEN" in body and "secret-token" in body


def test_bad_host_rejected(secured):
    _, client = secured
    r = client.get("/api/state", headers={"host": "evil.example", "x-api-token": "secret-token"})
    assert r.status_code == 400


def test_cross_origin_write_rejected(secured):
    _, client = secured
    r = client.post(
        "/api/next",
        headers={"x-api-token": "secret-token", "origin": "http://evil.example"},
    )
    assert r.status_code == 403


def test_resource_needs_no_token(secured):
    # The iframe loads /resource itself and can't attach a header; it stays open
    # (it only serves the user's own book bytes, under a strict CSP).
    _, client = secured
    assert client.get("/resource/OEBPS/ch1.xhtml").status_code == 200


# ---- 0.4 review: progress reaches the browser (payload-level) ------------- #
def test_state_payload_includes_progress_after_reopen(tmp_path, epub3_path):
    from epubreader.session.storage import JsonProgressStore

    sp = tmp_path / "state.json"
    first = WebFrontend(ReaderSession(JsonProgressStore(sp)))
    first.open_path(str(epub3_path))
    first.report_progress(0.625)
    first.session.close()                       # persist the position

    # A fresh reader over the same store must hand the browser the saved
    # position, not start at the top.
    second = WebFrontend(ReaderSession(JsonProgressStore(sp)))
    second.open_path(str(epub3_path))
    client = TestClient(create_app(second))
    section = client.get("/api/state").json()["section"]
    assert section["progress"] == 0.625


def test_state_payload_includes_ordinal(web):
    _, client = web
    hit = client.get("/api/search", params={"q": "World"}).json()[0]
    section = client.post("/api/search/goto", json={"hit": hit}).json()["section"]
    assert "highlight_ordinal" in section


# ---- 0.4 review: /api/open removed from the HTTP surface ------------------ #
def test_api_open_route_is_gone(web):
    _, client = web
    r = client.post("/api/open", json={"path": "/etc/passwd"})
    assert r.status_code == 404


# ---- 0.4 review: streamed upload still opens and cleans up ---------------- #
def test_streamed_upload_opens_and_swaps_temp(empty_client, epub3_path, epub2_path):
    from pathlib import Path

    frontend, client = empty_client
    client.post("/api/upload", params={"name": "a.epub"}, content=Path(epub3_path).read_bytes())
    first = frontend._temp_dir
    assert first and Path(first).is_dir()
    client.post("/api/upload", params={"name": "b.epub"}, content=Path(epub2_path).read_bytes())
    assert frontend._temp_dir != first
    assert not Path(first).exists()          # previous upload cleaned up


def test_failed_upload_preserves_open_book(web, epub3_path):
    frontend, client = web
    assert client.get("/api/state").json()["is_open"]
    # Garbage upload must fail without tearing down the currently open book.
    assert client.post("/api/upload", content=b"not an epub").status_code == 400
    assert client.get("/api/state").json()["is_open"]


def test_oversized_upload_leaves_no_temp_dir(empty_client, monkeypatch):
    import glob
    import tempfile

    from epubreader.frontends.web import server

    monkeypatch.setattr(server, "_MAX_UPLOAD_BYTES", 100)
    _, client = empty_client
    pattern = str(tempfile.gettempdir()) + "/epubreader-*"
    before = set(glob.glob(pattern))
    r = client.post("/api/upload", content=b"x" * 500)   # oversized
    assert r.status_code == 413
    # The streamed temp file/dir must be cleaned up, not stranded.
    assert set(glob.glob(pattern)) == before


def test_settings_change_reflected_in_state(web):
    _, client = web
    state = client.post(
        "/api/settings", json={"theme": "sepia", "font_scale": 1.4, "allow_scripts": False}
    ).json()
    assert state["settings"]["theme"] == "sepia"
    assert state["settings"]["font_scale"] == 1.4


# ---- upload (browser file picker / drag-and-drop) ------------------------- #
@pytest.fixture()
def empty_client():
    frontend = WebFrontend(ReaderSession(MemoryProgressStore()))
    return frontend, TestClient(create_app(frontend))


def test_upload_opens_book(empty_client, epub3_path):
    from pathlib import Path

    frontend, client = empty_client
    data = Path(epub3_path).read_bytes()
    state = client.post("/api/upload", params={"name": "My Book.epub"}, content=data).json()
    assert state["is_open"] is True
    assert state["section"]["key"] == "OEBPS/ch1.xhtml"
    # And the just-uploaded book's resources are now served.
    assert client.get("/resource/OEBPS/ch1.xhtml").status_code == 200


def test_upload_rejects_non_epub_bytes(empty_client):
    _, client = empty_client
    assert client.post("/api/upload", content=b"not a zip").status_code == 400


def test_upload_rejects_empty_body(empty_client):
    _, client = empty_client
    assert client.post("/api/upload", content=b"").status_code == 400


def test_upload_filename_is_sanitized():
    from epubreader.frontends.web.frontend import _safe_filename

    safe = _safe_filename("../../etc/passwd")
    assert "/" not in safe and ".." not in safe
    assert safe.endswith(".epub")


def test_second_upload_cleans_previous_temp(empty_client, epub3_path, epub2_path):
    from pathlib import Path

    frontend, client = empty_client
    client.post("/api/upload", params={"name": "a.epub"}, content=Path(epub3_path).read_bytes())
    first_temp = frontend._temp_dir
    assert first_temp and Path(first_temp).is_dir()
    client.post("/api/upload", params={"name": "b.epub"}, content=Path(epub2_path).read_bytes())
    # The new upload's temp exists; the previous one has been cleaned up.
    assert frontend._temp_dir != first_temp
    assert Path(frontend._temp_dir).is_dir()
    assert not Path(first_temp).exists()
