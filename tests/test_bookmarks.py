# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Bookmarks: session management and cross-store persistence."""

from __future__ import annotations

from epubreader.core.locators import Bookmark, Locator
from epubreader.session.session import ReaderSession
from epubreader.session.storage import JsonProgressStore, MemoryProgressStore


def test_add_bookmark_captures_current_position(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    session.next_section()  # move to spine 1
    bm = session.add_bookmark("my spot")
    assert bm.label == "my spot"
    assert bm.locator.spine_index == 1
    assert bm.id and bm.created_at
    assert [b.id for b in session.bookmarks()] == [bm.id]


def test_blank_label_defaults_to_section_title(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    bm = session.add_bookmark()          # spine 0 → TOC label "Chapter One"
    assert bm.label == "Chapter One"


def test_remove_bookmark_by_object_and_by_id(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    a = session.add_bookmark("a")
    b = session.add_bookmark("b")
    assert session.remove_bookmark(a) is True
    assert session.remove_bookmark(b.id) is True
    assert session.bookmarks() == []
    assert session.remove_bookmark("nonexistent") is False


def test_go_to_bookmark_restores_locator(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    session.next_section()
    session.report_progress(0.5)
    bm = session.add_bookmark()
    session.go_to_spine(0)
    session.go_to_bookmark(bm)
    assert session.locator().spine_index == 1


def test_bookmarks_persist_across_sessions_via_json(tmp_path, epub3_path):
    path = tmp_path / "state.json"
    first = ReaderSession(JsonProgressStore(path))
    first.open(epub3_path)
    first.add_bookmark("persist me")
    first.close()

    # A brand-new session over the same JSON file must see the bookmark.
    second = ReaderSession(JsonProgressStore(path))
    second.open(epub3_path)
    labels = [b.label for b in second.bookmarks()]
    assert "persist me" in labels


def test_bookmarks_are_scoped_per_book(epub3_path, epub2_path):
    store = MemoryProgressStore()
    session = ReaderSession(store)
    session.open(epub3_path)
    session.add_bookmark("epub3 mark")
    session.open(epub2_path)  # switch books
    # The second book starts with no bookmarks of its own.
    assert session.bookmarks() == []


def test_close_clears_bookmark_cache(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    session.add_bookmark("x")
    session.close()
    assert session.bookmarks() == []


def test_bookmark_round_trips_through_dict():
    bm = Bookmark(
        id="abc",
        locator=Locator(spine_index=2, progress=0.25, fragment="frag"),
        label="l",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert Bookmark.from_dict(bm.to_dict()) == bm
