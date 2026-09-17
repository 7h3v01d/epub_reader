# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The PyQt6 frontend: a main window that presents a :class:`ReaderSession`.

This is one concrete implementation of :class:`ReaderFrontend`. It knows about
widgets and Qt; it does not know how to parse EPUBs or track position — that all
lives in the engine and session it drives. Swap this class for a web server that
implements the same five methods and the rest of the stack is untouched.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...core.locators import Bookmark
from ...core.models import Metadata, NavPoint
from ...core.search import SearchHit
from ...frontend.base import ReaderFrontend
from ...session.session import ReaderSession, RenderedSection
from ...session.settings import ReaderSettings
from . import theme
from .panels import BookmarksPanel, SearchPanel
from .view import ReaderView
from .worker import open_book_async


class ReaderWindow(QMainWindow, ReaderFrontend):
    """The Qt reading window."""

    def __init__(self, session: ReaderSession) -> None:
        # One cooperative super().__init__() initialises QMainWindow and, down
        # the MRO, ReaderFrontend. The session is then bound explicitly — see
        # ReaderFrontend for why binding is separate from construction.
        super().__init__()
        self.bind_session(session)

        self.setWindowTitle("epubreader")
        self.resize(1100, 800)

        self._view = ReaderView(self)
        self._view.progress_changed.connect(self.session.report_progress)
        self._view.external_link_requested.connect(self._on_external_link)
        self.setCentralWidget(self._view)
        self._view.apply_settings(self.session.settings())

        self._toc_tree = QTreeWidget()
        self._toc_tree.setHeaderHidden(True)
        self._toc_tree.itemActivated.connect(self._on_toc_activated)
        dock = QDockWidget("Contents", self)
        dock.setWidget(self._toc_tree)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._toc_dock = dock

        # Search + bookmarks live on the right, tabbed together.
        self._search_panel = SearchPanel()
        self._search_panel.search_requested.connect(self._on_search)
        self._search_panel.hit_activated.connect(self._on_hit_activated)
        search_dock = QDockWidget("Search", self)
        search_dock.setWidget(self._search_panel)
        search_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, search_dock)
        self._search_dock = search_dock

        self._bookmarks_panel = BookmarksPanel()
        self._bookmarks_panel.add_requested.connect(self._on_add_bookmark)
        self._bookmarks_panel.remove_requested.connect(self._on_remove_bookmark)
        self._bookmarks_panel.bookmark_activated.connect(self._on_bookmark_activated)
        bookmarks_dock = QDockWidget("Bookmarks", self)
        bookmarks_dock.setWidget(self._bookmarks_panel)
        bookmarks_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, bookmarks_dock)
        self._bookmarks_dock = bookmarks_dock
        self.tabifyDockWidget(search_dock, bookmarks_dock)
        search_dock.raise_()

        self._status = QLabel("No book open")
        self._status.setObjectName("StatusLabel")
        self.statusBar().addWidget(self._status)

        self._build_toolbar()
        self.setStyleSheet(theme.QSS)
        self._refresh_nav_actions()

    # ---- toolbar --------------------------------------------------------- #
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        open_act = QAction("Open", self)
        open_act.triggered.connect(self._choose_file)
        tb.addAction(open_act)

        toc_act = QAction("Contents", self)
        toc_act.setCheckable(True)
        toc_act.setChecked(True)
        toc_act.triggered.connect(lambda v: self._toc_dock.setVisible(v))
        tb.addAction(toc_act)

        find_act = QAction("Find", self)
        find_act.setShortcut(QKeySequence.StandardKey.Find)  # Ctrl+F
        find_act.triggered.connect(self._focus_search)
        tb.addAction(find_act)

        self._bookmark_act = QAction("Bookmark", self)
        self._bookmark_act.setShortcut(QKeySequence("Ctrl+D"))
        self._bookmark_act.triggered.connect(self._on_add_bookmark)
        tb.addAction(self._bookmark_act)
        tb.addSeparator()

        self._prev_act = QAction("‹ Prev", self)
        self._prev_act.triggered.connect(self.session.prev_section)
        tb.addAction(self._prev_act)
        self._next_act = QAction("Next ›", self)
        self._next_act.triggered.connect(self.session.next_section)
        tb.addAction(self._next_act)
        tb.addSeparator()

        s = self.session.settings()

        tb.addWidget(QLabel(" Theme "))
        self._theme_box = QComboBox()
        self._theme_box.addItems(["obsidian", "sepia", "light"])
        self._theme_box.setCurrentText(s.theme)
        self._theme_box.currentTextChanged.connect(self._on_settings_changed)
        tb.addWidget(self._theme_box)

        tb.addWidget(QLabel(" Scale "))
        self._scale_box = QDoubleSpinBox()
        self._scale_box.setRange(0.6, 2.5)
        self._scale_box.setSingleStep(0.1)
        self._scale_box.setValue(s.font_scale)
        self._scale_box.valueChanged.connect(self._on_settings_changed)
        tb.addWidget(self._scale_box)

        self._scripts_box = QCheckBox("Allow book scripts")
        self._scripts_box.setChecked(s.allow_scripts)
        self._scripts_box.stateChanged.connect(self._on_settings_changed)
        tb.addWidget(self._scripts_box)

    def _on_settings_changed(self, *_: object) -> None:
        new = ReaderSettings(
            theme=self._theme_box.currentText(),
            font_scale=self._scale_box.value(),
            allow_scripts=self._scripts_box.isChecked(),
        )
        self._view.apply_settings(new)
        self.session.update_settings(new)

    # ---- file open ------------------------------------------------------- #
    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open EPUB", str(Path.home()), "EPUB files (*.epub);;All files (*)"
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        self._status.setText(f"Opening {Path(path).name} …")
        self._prev_act.setEnabled(False)
        self._next_act.setEnabled(False)
        # Tag each open with a generation so a slow earlier open finishing after
        # a later one can't replace the user's most recent selection.
        self._open_generation = getattr(self, "_open_generation", 0) + 1
        generation = self._open_generation
        open_book_async(
            path,
            lambda book: self._on_book_opened(book, generation),
            self.report_error,
        )

    def _on_book_opened(self, book, generation: int = 0) -> None:
        # Runs on the GUI thread: safe to touch the view/session.
        if generation and generation != getattr(self, "_open_generation", generation):
            # A newer open superseded this one; discard the stale result.
            book.close()
            return
        self._view.set_book(book)
        self.session.adopt_book(book)
        # Bookmarks are book-scoped; refresh the panel now the book is loaded.
        self._bookmarks_panel.set_bookmarks(self.session.bookmarks())
        self._search_panel.set_results([])

    def _on_external_link(self, url: QUrl) -> None:
        # Deny-first: external links are surfaced, not auto-opened.
        self._status.setText(f"External link blocked: {url.toString()}")

    # ---- ReaderFrontend contract ---------------------------------------- #
    def display_section(self, section: RenderedSection) -> None:
        self._view.apply_settings(self.session.settings())
        self._view.show_section(section)
        self._refresh_nav_actions(section)
        self._status.setText(
            f"{section.title}  —  {section.spine_index + 1}/{section.total_sections}"
        )

    def display_toc(self, toc: tuple[NavPoint, ...]) -> None:
        self._toc_tree.clear()

        def add(points: tuple[NavPoint, ...], parent) -> None:
            for point in points:
                item = QTreeWidgetItem([point.label])
                item.setData(0, Qt.ItemDataRole.UserRole, (point.key, point.fragment))
                (parent.addChild if parent else self._toc_tree.addTopLevelItem)(item)
                if point.children:
                    add(point.children, item)

        add(toc, None)
        self._toc_tree.expandAll()

    def display_metadata(self, metadata: Metadata) -> None:
        creators = ", ".join(metadata.creators)
        title = metadata.title + (f" — {creators}" if creators else "")
        self.setWindowTitle(f"{title}  ·  epubreader")
        # The session resets scripts off for every newly opened book (fail-
        # closed); reflect that in the toolbar without re-pushing settings.
        self._scripts_box.blockSignals(True)
        self._scripts_box.setChecked(self.session.settings().allow_scripts)
        self._scripts_box.blockSignals(False)

    def report_error(self, message: str) -> None:
        self._status.setObjectName("ErrorLabel")
        self._status.setStyleSheet(f"color: {theme.RED};")
        self._status.setText(f"Error: {message}")
        self._refresh_nav_actions()

    def run(self) -> int:
        self.show()
        return QApplication.instance().exec()

    # ---- helpers --------------------------------------------------------- #
    def _on_toc_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        key, fragment = data
        if key:
            try:
                self.session.go_to_key(key, fragment=fragment)
            except Exception as exc:  # noqa: BLE001
                self.report_error(str(exc))

    def _refresh_nav_actions(self, section: RenderedSection | None = None) -> None:
        if section is None:
            section = self.session.current_section()
        has = section is not None
        self._prev_act.setEnabled(has and not section.is_first)
        self._next_act.setEnabled(has and not section.is_last)

    # ---- search ---------------------------------------------------------- #
    def _focus_search(self) -> None:
        self._search_dock.setVisible(True)
        self._search_dock.raise_()
        self._search_panel.focus_field()

    def _on_search(self, query: str, case_sensitive: bool, whole_word: bool) -> None:
        if not self.session.is_open:
            return
        try:
            hits = self.session.search(
                query, case_sensitive=case_sensitive, whole_word=whole_word
            )
        except Exception as exc:  # noqa: BLE001
            self.report_error(str(exc))
            return
        self._search_panel.set_results(hits)

    def _on_hit_activated(self, hit: SearchHit) -> None:
        try:
            self.session.go_to_search_hit(hit)
        except Exception as exc:  # noqa: BLE001
            self.report_error(str(exc))

    # ---- bookmarks ------------------------------------------------------- #
    def _on_add_bookmark(self) -> None:
        if not self.session.is_open:
            return
        try:
            self.session.add_bookmark()
        except Exception as exc:  # noqa: BLE001
            self.report_error(str(exc))
            return
        self._bookmarks_panel.set_bookmarks(self.session.bookmarks())
        self._bookmarks_dock.setVisible(True)
        self._bookmarks_dock.raise_()

    def _on_remove_bookmark(self, bookmark: Bookmark) -> None:
        self.session.remove_bookmark(bookmark)
        self._bookmarks_panel.set_bookmarks(self.session.bookmarks())

    def _on_bookmark_activated(self, bookmark: Bookmark) -> None:
        try:
            self.session.go_to_bookmark(bookmark)
        except Exception as exc:  # noqa: BLE001
            self.report_error(str(exc))
