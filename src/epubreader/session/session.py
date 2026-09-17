# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The stateful reading session — the model a frontend drives.

A :class:`ReaderSession` owns an open :class:`Book`, the current :class:`Locator`
and the :class:`ReaderSettings`, and mediates navigation. It emits nothing
toolkit-specific: state changes are published through plain callbacks, so a Qt
frontend can adapt them to signals while a web frontend pushes them over a
socket. The session produces transport-neutral :class:`RenderedSection` values;
a frontend maps ``section.key`` to whatever URL its renderer speaks.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..core.book import Book
from ..core.exceptions import NavigationError
from ..core.locators import Bookmark, Locator
from ..core.models import Metadata, NavPoint, SpineItem
from ..core.search import SearchHit, search_book, section_titles
from .settings import ReaderSettings
from .storage import ProgressStore

# Listener signatures kept intentionally loose (frontend adapts them).
SectionListener = Callable[["RenderedSection"], None]
ErrorListener = Callable[[str], None]
BookOpenedListener = Callable[[], None]


@dataclass(frozen=True)
class RenderedSection:
    """A transport-neutral description of the section to display.

    It carries no URL. The frontend turns ``key`` into a renderer address
    (``epub://…`` for Qt, ``/resource/…`` for a web server) itself. That is the
    seam that keeps the UI replaceable.
    """

    spine_index: int
    key: str
    media_type: str
    title: str
    fragment: str = ""
    total_sections: int = 0
    #: Text a frontend should highlight after rendering (set when navigating to
    #: a search hit). Empty for ordinary navigation. Toolkit-neutral: Qt maps it
    #: to ``findText``, a browser to its native find.
    highlight: str = ""
    #: Which occurrence of ``highlight`` to reveal (0-based) — a frontend steps
    #: to the Nth match so distinct search hits for the same word land correctly.
    highlight_ordinal: int = 0
    #: Stored reading position within this section (0..1). A frontend restores
    #: scroll to it after load when there is no fragment to honour instead.
    progress: float = 0.0

    @property
    def is_last(self) -> bool:
        return self.spine_index >= self.total_sections - 1

    @property
    def is_first(self) -> bool:
        return self.spine_index <= 0


class ReaderSession:
    """Drives reading state over a single open book."""

    def __init__(self, store: ProgressStore) -> None:
        self._store = store
        self._book: Optional[Book] = None
        self._locator = Locator(spine_index=0)
        self._settings = store.get_settings()
        self._bookmarks: list[Bookmark] = []
        self._pending_highlight: str = ""
        self._pending_ordinal: int = 0
        self._section_listeners: list[SectionListener] = []
        self._error_listeners: list[ErrorListener] = []
        self._book_opened_listeners: list[BookOpenedListener] = []

    # ---- listener registration ------------------------------------------ #
    def on_section(self, fn: SectionListener) -> None:
        self._section_listeners.append(fn)

    def on_error(self, fn: ErrorListener) -> None:
        self._error_listeners.append(fn)

    def on_book_opened(self, fn: BookOpenedListener) -> None:
        """Fires once when a new book is adopted, before its first section.

        Frontends refresh chrome that belongs to the *book* (metadata, the
        table of contents) here, so it is not rebuilt on every page turn.
        """
        self._book_opened_listeners.append(fn)

    def _emit_section(self) -> None:
        section = self.current_section()
        if section is not None:
            for fn in list(self._section_listeners):
                fn(section)

    def _emit_book_opened(self) -> None:
        for fn in list(self._book_opened_listeners):
            fn()

    def _emit_error(self, message: str) -> None:
        for fn in list(self._error_listeners):
            fn(message)

    # ---- lifecycle ------------------------------------------------------- #
    def open(self, path: str | Path, *, resume: bool = True) -> None:
        """Open a book (blocking). Resumes to the stored locator by default.

        This is deliberately synchronous and Qt-free; a frontend that needs
        responsiveness opens the :class:`Book` on its own worker thread and
        then calls :meth:`adopt_book` on the GUI thread instead.

        Transactional: the new book is opened *before* the current one is
        touched, so a failed open leaves the currently open book intact.
        """
        book = Book.open(path)          # may raise — current book still open
        self.adopt_book(book, resume=resume)

    def adopt_book(self, book: Book, *, resume: bool = True) -> None:
        """Adopt an already-opened :class:`Book` and emit its first section.

        Split out from :meth:`open` so a frontend can do the slow
        :meth:`Book.open` on a worker thread, then hand the finished book here
        on the GUI thread where section emission is safe.
        """
        if self._book is not None and self._book is not book:
            self.close()
        self._book = book
        # Fail-closed: every newly opened book starts with scripts disabled,
        # regardless of a previously persisted preference, so a trusted book's
        # opt-in can never be inherited by an unrelated (possibly hostile) one.
        if self._settings.allow_scripts:
            self._settings = dataclasses.replace(self._settings, allow_scripts=False)
            self._store.set_settings(self._settings)
        stored = self._store.get_locator(book.book_id) if resume else None
        self._locator = stored or Locator(spine_index=0)
        self._clamp_locator()
        self._bookmarks = self._store.get_bookmarks(book.book_id)
        self._emit_book_opened()
        self._emit_section()

    def close(self) -> None:
        if self._book is not None:
            self._persist()
            self._book.close()
            self._book = None
        self._bookmarks = []
        self._pending_highlight = ""

    @property
    def is_open(self) -> bool:
        return self._book is not None

    @property
    def book(self) -> Book:
        if self._book is None:
            raise NavigationError("no book is open")
        return self._book

    # ---- metadata / structure ------------------------------------------- #
    def metadata(self) -> Metadata:
        return self.book.metadata

    def toc(self) -> tuple[NavPoint, ...]:
        return self.book.toc

    def spine(self) -> tuple[SpineItem, ...]:
        return self.book.spine

    def locator(self) -> Locator:
        return self._locator

    # ---- rendering ------------------------------------------------------- #
    def current_section(self) -> Optional[RenderedSection]:
        if self._book is None:
            return None
        spine = self._book.spine
        idx = self._locator.spine_index
        item = spine[idx]
        return RenderedSection(
            spine_index=idx,
            key=item.key,
            media_type=item.media_type,
            title=self.metadata().title,
            fragment=self._locator.fragment,
            total_sections=len(spine),
            highlight=self._pending_highlight,
            highlight_ordinal=self._pending_ordinal,
            progress=self._locator.progress,
        )

    # ---- navigation ------------------------------------------------------ #
    def go_to_spine(self, index: int, *, fragment: str = "", progress: float = 0.0) -> None:
        spine = self.book.spine
        if not 0 <= index < len(spine):
            raise NavigationError(f"spine index out of range: {index}")
        self._locator = Locator(spine_index=index, progress=progress, fragment=fragment)
        self._persist()
        self._emit_section()

    def next_section(self) -> bool:
        idx = self._locator.spine_index + 1
        if idx >= len(self.book.spine):
            return False
        self.go_to_spine(idx)
        return True

    def prev_section(self) -> bool:
        idx = self._locator.spine_index - 1
        if idx < 0:
            return False
        self.go_to_spine(idx)
        return True

    def go_to_key(self, key: str, *, fragment: str = "") -> None:
        """Jump to the spine document whose archive key is ``key``."""
        index = self.book.spine_index_for_key(key)
        if index is None:
            raise NavigationError(f"no spine entry for key: {key}")
        self.go_to_spine(index, fragment=fragment)

    def go_to_nav_point(self, point: NavPoint) -> None:
        self.go_to_key(point.key, fragment=point.fragment)

    # ---- search ---------------------------------------------------------- #
    def search(
        self,
        query: str,
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
        max_results: int = 200,
    ) -> list[SearchHit]:
        """Full-text search across the open book (engine does the work)."""
        return search_book(
            self.book,
            query,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            max_results=max_results,
        )

    def go_to_search_hit(self, hit: SearchHit) -> None:
        """Navigate to a hit's section and ask the frontend to highlight it."""
        self._pending_highlight = hit.query
        self._pending_ordinal = hit.ordinal
        try:
            self.go_to_spine(hit.spine_index)
        finally:
            # The highlight is one-shot: it rode along with the emitted section
            # and must not leak into later re-renders (e.g. a settings change).
            self._pending_highlight = ""
            self._pending_ordinal = 0

    # ---- bookmarks ------------------------------------------------------- #
    def bookmarks(self) -> list[Bookmark]:
        """Bookmarks saved for the current book, newest position aside."""
        return list(self._bookmarks)

    def add_bookmark(self, label: str = "") -> Bookmark:
        """Save the current position. A blank label defaults to the section."""
        book = self.book  # raises if no book is open
        text = label.strip() or self._default_bookmark_label()
        bookmark = Bookmark(
            id=uuid.uuid4().hex,
            locator=self._locator,
            label=text,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        # Atomic append at the store, then refresh from it — so a concurrent
        # reader's bookmarks are preserved rather than overwritten by our cache.
        self._bookmarks = self._store.add_bookmark(book.book_id, bookmark)
        return bookmark

    def remove_bookmark(self, bookmark: Bookmark | str) -> bool:
        """Remove a bookmark (by object or id). Returns whether one was removed."""
        target = bookmark.id if isinstance(bookmark, Bookmark) else str(bookmark)
        before = {b.id for b in self._bookmarks}
        self._bookmarks = self._store.remove_bookmark(self.book.book_id, target)
        return target in before

    def go_to_bookmark(self, bookmark: Bookmark) -> None:
        loc = bookmark.locator
        self.go_to_spine(loc.spine_index, fragment=loc.fragment, progress=loc.progress)

    def _default_bookmark_label(self) -> str:
        titles = section_titles(self.book)
        idx = self._locator.spine_index
        key = self.book.spine[idx].key
        return titles.get(key) or f"Section {idx + 1}"

    # ---- progress within the current section ---------------------------- #
    def report_progress(self, progress: float) -> None:
        """Record scroll fraction reported by the view (does not re-render)."""
        self._locator = Locator(
            spine_index=self._locator.spine_index,
            progress=progress,
            fragment=self._locator.fragment,
        )
        self._persist()

    # ---- settings -------------------------------------------------------- #
    def settings(self) -> ReaderSettings:
        return self._settings

    def update_settings(self, settings: ReaderSettings) -> None:
        self._settings = settings.clamped()
        self._store.set_settings(self._settings)
        # Re-render so a theme/scale change is reflected immediately.
        if self._book is not None:
            self._emit_section()

    # ---- internals ------------------------------------------------------- #
    def _clamp_locator(self) -> None:
        spine = self.book.spine
        idx = self._locator.spine_index
        if not 0 <= idx < len(spine):
            self._locator = Locator(spine_index=0)

    def _persist(self) -> None:
        if self._book is not None:
            self._store.set_locator(self._book.book_id, self._locator)
