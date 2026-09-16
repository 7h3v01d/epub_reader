# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Dock panels for search and bookmarks.

Kept as standalone widgets that speak only in Qt signals and the engine's plain
data types (:class:`SearchHit`, :class:`Bookmark`). They never touch the session
directly — the window wires their signals to session calls — so the panels stay
dumb and the session stays UI-free.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.locators import Bookmark
from ...core.search import SearchHit

_HIT_ROLE = Qt.ItemDataRole.UserRole
_BOOKMARK_ROLE = Qt.ItemDataRole.UserRole


class SearchPanel(QWidget):
    """A query box plus a results list. Emits requests; renders results."""

    search_requested = pyqtSignal(str, bool, bool)  # query, case_sensitive, whole_word
    hit_activated = pyqtSignal(object)              # SearchHit

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._field = QLineEdit()
        self._field.setPlaceholderText("Search book…")
        self._field.returnPressed.connect(self._emit_search)
        layout.addWidget(self._field)

        opts = QHBoxLayout()
        self._case_box = QCheckBox("Match case")
        self._word_box = QCheckBox("Whole word")
        self._case_box.stateChanged.connect(self._emit_search)
        self._word_box.stateChanged.connect(self._emit_search)
        opts.addWidget(self._case_box)
        opts.addWidget(self._word_box)
        opts.addStretch(1)
        layout.addLayout(opts)

        self._count = QLabel("")
        self._count.setObjectName("StatusLabel")
        layout.addWidget(self._count)

        self._results = QListWidget()
        self._results.setUniformItemSizes(True)
        self._results.setWordWrap(True)
        self._results.itemActivated.connect(self._on_activated)
        self._results.itemClicked.connect(self._on_activated)
        layout.addWidget(self._results, 1)

    def focus_field(self) -> None:
        self._field.setFocus()
        self._field.selectAll()

    def _emit_search(self, *_: object) -> None:
        query = self._field.text().strip()
        if query:
            self.search_requested.emit(
                query, self._case_box.isChecked(), self._word_box.isChecked()
            )
        else:
            self.set_results([])

    def set_results(self, hits: list[SearchHit]) -> None:
        self._results.clear()
        for hit in hits:
            label = hit.snippet if not hit.section_title else f"{hit.section_title} — {hit.snippet}"
            item = QListWidgetItem(label)
            item.setData(_HIT_ROLE, hit)
            self._results.addItem(item)
        if hits:
            self._count.setText(f"{len(hits)} match{'es' if len(hits) != 1 else ''}")
        else:
            self._count.setText("No matches" if self._field.text().strip() else "")

    def _on_activated(self, item: QListWidgetItem) -> None:
        hit = item.data(_HIT_ROLE)
        if isinstance(hit, SearchHit):
            self.hit_activated.emit(hit)


class BookmarksPanel(QWidget):
    """A list of saved positions with add/remove controls."""

    add_requested = pyqtSignal()
    remove_requested = pyqtSignal(object)       # Bookmark
    bookmark_activated = pyqtSignal(object)     # Bookmark

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        add_btn = QPushButton("Bookmark this page")
        add_btn.clicked.connect(self.add_requested)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._emit_remove)
        self._remove_btn.setEnabled(False)
        controls.addWidget(add_btn, 1)
        controls.addWidget(self._remove_btn)
        layout.addLayout(controls)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

    def set_bookmarks(self, bookmarks: list[Bookmark]) -> None:
        self._list.clear()
        for bm in bookmarks:
            item = QListWidgetItem(bm.label or f"Section {bm.locator.spine_index + 1}")
            item.setData(_BOOKMARK_ROLE, bm)
            self._list.addItem(item)
        self._remove_btn.setEnabled(False)

    def _selected_bookmark(self) -> Bookmark | None:
        item = self._list.currentItem()
        bm = item.data(_BOOKMARK_ROLE) if item else None
        return bm if isinstance(bm, Bookmark) else None

    def _on_selection_changed(self) -> None:
        self._remove_btn.setEnabled(self._selected_bookmark() is not None)

    def _emit_remove(self) -> None:
        bm = self._selected_bookmark()
        if bm is not None:
            self.remove_requested.emit(bm)

    def _on_activated(self, item: QListWidgetItem) -> None:
        bm = item.data(_BOOKMARK_ROLE)
        if isinstance(bm, Bookmark):
            self.bookmark_activated.emit(bm)
