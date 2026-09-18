# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""A web frontend for the reader — the payoff of the replaceable-UI design.

This subclasses the very same :class:`ReaderFrontend` the Qt window does and
drives the very same :class:`ReaderSession`. Nothing in ``core`` or ``session``
changes; only the presentation differs.

The contract is push-based (the session calls ``display_section`` and friends),
but HTTP is pull-based (the browser asks). The bridge is a small **view-model**:
each ``display_*`` callback simply records the latest state, and the HTTP routes
serialise that record on demand. So a request that mutates state — "next
section" — calls the session, whose emit runs ``display_section`` synchronously,
which updates the view-model the same response then returns.

Section content is mapped to transport exactly as the design intends: the
frontend turns ``section.key`` into ``/resource/<key>``, and that route serves
``session.book.read_resource(key)`` through :func:`render.inject_stylesheet`.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from ...core.locators import Bookmark
from ...core.models import Metadata, NavPoint
from ...core.search import SearchHit
from ...frontend.base import ReaderFrontend
from ...render import inject_stylesheet, reader_stylesheet
from ...session.session import ReaderSession, RenderedSection
from ...session.settings import ReaderSettings

_HTML_MEDIA = ("application/xhtml+xml", "text/html", "application/html")


def accepted_hosts(bind_host: str) -> set[str]:
    """Host header values to accept, given the address the server binds to.

    The bind address and the acceptable Host are not the same thing: a wildcard
    bind (``0.0.0.0`` / ``::``) is reached by clients using the machine's real
    address, not the wildcard, so those addresses are resolved and added — while
    still refusing arbitrary Host values (DNS-rebinding protection is kept).
    """
    hosts = {"127.0.0.1", "localhost", "::1"}
    h = (bind_host or "").lower()
    if h in {"0.0.0.0", "::", ""}:
        import socket

        try:
            name = socket.gethostname()
            hosts.add(name.lower())
            for info in socket.getaddrinfo(name, None):
                hosts.add(str(info[4][0]).lower())
        except OSError:
            pass
    else:
        hosts.add(h)
    return hosts


class WebFrontend(ReaderFrontend):
    """Presents a :class:`ReaderSession` over HTTP.

    Scoped to a single reader and one open book at a time, which is the right
    shape for a local-first personal reader. A :class:`threading.Lock` serialises
    session access so overlapping requests can't interleave mutations.
    """

    def __init__(self, session: ReaderSession) -> None:
        super().__init__()
        self.bind_session(session)
        self._lock = threading.RLock()
        self._temp_dir: Optional[str] = None
        self._section: Optional[RenderedSection] = None
        self._metadata: Optional[Metadata] = None
        self._toc: tuple[NavPoint, ...] = ()
        self._error: str = ""

    # ---- ReaderFrontend contract: capture state into the view-model ------ #
    def display_section(self, section: RenderedSection) -> None:
        self._section = section

    def display_toc(self, toc: tuple[NavPoint, ...]) -> None:
        self._toc = toc

    def display_metadata(self, metadata: Metadata) -> None:
        self._metadata = metadata

    def report_error(self, message: str) -> None:
        self._error = message

    def run(self, host: str = "127.0.0.1", port: int = 8000) -> int:
        """Serve the reader. Imported lazily so tests need no uvicorn."""
        import secrets

        import uvicorn

        from .server import create_app

        token = secrets.token_urlsafe(24)
        # Host/Origin pinning stays on for every bind. For a wildcard bind the
        # machine's real addresses are resolved and accepted, so a LAN client
        # using the actual IP works while arbitrary Host values are still refused.
        allowed = accepted_hosts(host)
        app = create_app(self, token=token, allowed_hosts=allowed)
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    # ---- operations the routes call (all session access is locked) ------- #
    def open_path(self, path: str) -> dict:
        with self._lock:
            self._error = ""
            self.session.open(path)
            return self._state_locked()

    def open_bytes(self, data: bytes, name: str = "book.epub") -> dict:
        """Open a book from uploaded bytes (kept for direct/programmatic use).

        The HTTP upload route streams to disk instead (see prepare/adopt below);
        this convenience path buffers, so prefer the streaming lifecycle for
        untrusted network input.
        """
        with self._lock:
            new_dir, dest = self.prepare_upload(name)
            Path(dest).write_bytes(data)
            return self.adopt_upload(new_dir, dest)

    def prepare_upload(self, name: str) -> tuple[str, str]:
        """Create a private temp dir + destination path for an incoming upload."""
        new_dir = tempfile.mkdtemp(prefix="epubreader-")
        dest = str(Path(new_dir) / _safe_filename(name))
        return new_dir, dest

    def adopt_upload(self, new_dir: str, dest: str) -> dict:
        """Open the streamed file; on success swap it in and clean up the old one."""
        with self._lock:
            old_dir = self._temp_dir
            try:
                result = self.open_path(dest)
            except Exception:
                shutil.rmtree(new_dir, ignore_errors=True)
                raise
            self._temp_dir = new_dir
            if old_dir:
                shutil.rmtree(old_dir, ignore_errors=True)
            return result

    def abort_upload(self, new_dir: str) -> None:
        shutil.rmtree(new_dir, ignore_errors=True)

    def state(self) -> dict:
        with self._lock:
            return self._state_locked()

    def toc(self) -> list[dict]:
        with self._lock:
            return [_nav_payload(p) for p in self._toc]

    def go_next(self) -> dict:
        with self._lock:
            self.session.next_section()
            return self._state_locked()

    def go_prev(self) -> dict:
        with self._lock:
            self.session.prev_section()
            return self._state_locked()

    def go_to(self, *, key: str = "", fragment: str = "", spine_index: Optional[int] = None) -> dict:
        with self._lock:
            if spine_index is not None:
                self.session.go_to_spine(spine_index, fragment=fragment)
            elif key:
                self.session.go_to_key(key, fragment=fragment)
            return self._state_locked()

    def search(self, query: str, *, case_sensitive: bool, whole_word: bool) -> list[dict]:
        with self._lock:
            hits = self.session.search(
                query, case_sensitive=case_sensitive, whole_word=whole_word
            )
            return [h.to_dict() for h in hits]

    def go_to_hit(self, hit: dict) -> dict:
        with self._lock:
            self.session.go_to_search_hit(SearchHit.from_dict(hit))
            return self._state_locked()

    def bookmarks(self) -> list[dict]:
        with self._lock:
            return [_bookmark_payload(b) for b in self.session.bookmarks()]

    def add_bookmark(self, label: str = "") -> dict:
        with self._lock:
            self.session.add_bookmark(label)
            return {"bookmarks": [_bookmark_payload(b) for b in self.session.bookmarks()]}

    def remove_bookmark(self, bookmark_id: str) -> dict:
        with self._lock:
            self.session.remove_bookmark(bookmark_id)
            return {"bookmarks": [_bookmark_payload(b) for b in self.session.bookmarks()]}

    def go_to_bookmark(self, bookmark_id: str) -> dict:
        with self._lock:
            match = next((b for b in self.session.bookmarks() if b.id == bookmark_id), None)
            if match is not None:
                self.session.go_to_bookmark(match)
            return self._state_locked()

    def report_progress(self, progress: float) -> None:
        with self._lock:
            if self.session.is_open:
                self.session.report_progress(progress)

    def update_settings(self, *, theme: str, font_scale: float, allow_scripts: bool) -> dict:
        with self._lock:
            self.session.update_settings(
                ReaderSettings(theme=theme, font_scale=font_scale, allow_scripts=allow_scripts)
            )
            return self._state_locked()

    def resource(self, key: str) -> tuple[bytes, str]:
        """Serve one archive resource, theming HTML. Raises if the key is unknown.

        This is the deny-first choke point on the web side: ``read_resource``
        only returns keys present in the archive namelist, so a traversal or
        made-up path resolves to nothing and 404s.
        """
        with self._lock:
            resource = self.session.book.read_resource(key)
        data, media = resource.data, resource.media_type
        if any(media.startswith(m) for m in _HTML_MEDIA):
            css = reader_stylesheet(self.session.settings())
            data = inject_stylesheet(data, media, css)
        return data, media

    def script_policy(self) -> str:
        """CSP ``script-src`` for book content — always denied on the web.

        Book resources are served from the *same origin* as the reader shell, so
        an ``allow-same-origin`` iframe that also ran scripts could reach the
        parent document and the control-plane API. The web frontend therefore
        never executes book JavaScript; the ``allow_scripts`` setting only
        affects the desktop frontend, whose renderer is an isolated,
        network-blocked native profile with no parent document to escape to.
        """
        return "'none'"

    # ---- internals ------------------------------------------------------- #
    def _state_locked(self) -> dict:
        section = self._section
        payload = _section_payload(section) if section is not None else None
        # The highlight is one-shot end to end: hand it out once, then clear it
        # from the snapshot so a later poll doesn't re-trigger a search jump.
        if section is not None and section.highlight:
            self._section = dataclasses.replace(section, highlight="")
        meta = self._metadata
        return {
            "is_open": self.session.is_open,
            "section": payload,
            "metadata": (
                {"title": meta.title, "creators": list(meta.creators)}
                if meta is not None
                else None
            ),
            "settings": self.session.settings().to_dict() if self.session else None,
            "error": self._error,
        }


def _safe_filename(name: str) -> str:
    """Reduce an uploaded name to a safe basename (defends the temp path).

    Only the basename is kept, then restricted to a conservative character set,
    so a crafted upload name cannot traverse out of the temp directory.
    """
    base = os.path.basename(name or "")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._") or "book"
    if not base.lower().endswith(".epub"):
        base += ".epub"
    return base


def _section_payload(section: RenderedSection) -> dict:
    return {
        "spine_index": section.spine_index,
        "key": section.key,
        "media_type": section.media_type,
        "title": section.title,
        "fragment": section.fragment,
        "total_sections": section.total_sections,
        "is_first": section.is_first,
        "is_last": section.is_last,
        "highlight": section.highlight,
        "highlight_ordinal": section.highlight_ordinal,
        "highlight_case": section.highlight_case,
        "highlight_whole_word": section.highlight_whole_word,
        "highlight_prefix": section.highlight_prefix,
        "progress": section.progress,
    }


def _nav_payload(point: NavPoint) -> dict:
    return {
        "label": point.label,
        "key": point.key,
        "fragment": point.fragment,
        "children": [_nav_payload(c) for c in point.children],
    }


def _bookmark_payload(bookmark: Bookmark) -> dict:
    return {
        "id": bookmark.id,
        "label": bookmark.label,
        "spine_index": bookmark.locator.spine_index,
        "created_at": bookmark.created_at,
    }
