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


def test_script_policy_follows_allow_scripts(web):
    frontend, client = web
    assert "'none'" in frontend.script_policy()
    client.post("/api/settings", json={"theme": "obsidian", "font_scale": 1.0, "allow_scripts": True})
    csp = client.get("/resource/OEBPS/ch1.xhtml").headers["content-security-policy"]
    assert "script-src 'self' 'unsafe-inline'" in csp


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


def test_settings_change_reflected_in_state(web):
    _, client = web
    state = client.post(
        "/api/settings", json={"theme": "sepia", "font_scale": 1.4, "allow_scripts": False}
    ).json()
    assert state["settings"]["theme"] == "sepia"
    assert state["settings"]["font_scale"] == 1.4
