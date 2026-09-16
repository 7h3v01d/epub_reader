# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The reading surface: a QWebEngineView wired to the ``epub`` scheme.

The view owns a private :class:`QWebEngineProfile` (off-the-record, so nothing
about the book is cached to disk), installs the scheme handler and the
deny-first interceptor on it, and renders a section by loading its
``epub://book/<key>`` URL. Scroll fraction is reported back to the session
without executing any page script, honouring the deny-first posture.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ...core.book import Book
from ...session.session import RenderedSection
from ...session.settings import ReaderSettings
from .page import ReaderPage
from .scheme import DenyFirstInterceptor, EpubSchemeHandler, url_for_key


class ReaderView(QWebEngineView):
    """Renders book sections and reports reading progress."""

    progress_changed = pyqtSignal(float)
    external_link_requested = pyqtSignal(QUrl)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profile = QWebEngineProfile(self)  # off-the-record (no name)
        self._handler = EpubSchemeHandler(self)
        self._interceptor = DenyFirstInterceptor(self)
        self._profile.installUrlSchemeHandler(b"epub", self._handler)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = ReaderPage(self._profile, self)
        self._page.external_link_requested.connect(self.external_link_requested)
        self.setPage(self._page)
        self._page.scrollPositionChanged.connect(self._on_scroll)

        # Term to highlight once the next section finishes loading (from a
        # search hit). findText needs no page scripting, so it keeps the
        # deny-first posture intact.
        self._pending_find = ""
        self.loadFinished.connect(self._on_load_finished)

    # ---- configuration --------------------------------------------------- #
    def set_book(self, book: Optional[Book]) -> None:
        self._handler.set_book(book)

    def apply_settings(self, settings: ReaderSettings) -> None:
        self._handler.set_settings(settings)
        self._page.apply_settings(settings)

    # ---- rendering ------------------------------------------------------- #
    def show_section(self, section: RenderedSection) -> None:
        self._pending_find = section.highlight
        self.load(url_for_key(section.key, section.fragment))

    def _on_load_finished(self, ok: bool) -> None:
        # An empty term clears any previous highlight; a non-empty one selects
        # and scrolls to the first match.
        if ok:
            self._page.findText(self._pending_find)

    # ---- progress (no page scripting required) --------------------------- #
    def _on_scroll(self, *_: object) -> None:
        pos = self._page.scrollPosition()
        contents = self._page.contentsSize()
        viewport = float(self.height())
        scrollable = max(1.0, contents.height() - viewport)
        fraction = pos.y() / scrollable if scrollable > 0 else 0.0
        self.progress_changed.emit(max(0.0, min(1.0, fraction)))
