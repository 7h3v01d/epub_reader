# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Adversarial-review regression tests (engine / session / storage).

Each test pins a fix from the 0.3 review so the defect cannot silently return.
Web-frontend fixes live in test_web.py.
"""

from __future__ import annotations

import math
import zipfile

import pytest

from epubreader.core.book import Book
from epubreader.core.exceptions import InvalidEpubError
from epubreader.core.locators import Locator
from epubreader.session.session import ReaderSession
from epubreader.session.settings import ReaderSettings
from epubreader.session.storage import JsonProgressStore, MemoryProgressStore


# ---- transactional open --------------------------------------------------- #
def test_failed_open_preserves_current_book(epub3_path, tmp_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    assert session.is_open
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    with pytest.raises(InvalidEpubError):
        session.open(bad)
    # The working book must still be open after a failed replacement.
    assert session.is_open
    assert session.current_section().key == "OEBPS/ch1.xhtml"


# ---- fail-closed script permission ---------------------------------------- #
def test_opening_a_book_disables_scripts(epub3_path):
    store = MemoryProgressStore()
    store.set_settings(ReaderSettings(allow_scripts=True))   # a prior opt-in
    session = ReaderSession(store)
    session.open(epub3_path)
    # Every newly opened book starts fail-closed regardless of prior state.
    assert session.settings().allow_scripts is False


# ---- zip-bomb budgets ----------------------------------------------------- #
def _valid_epub_with_big_member(src, dst, size):
    # A structurally valid EPUB plus one oversized, highly-compressible member,
    # so the ONLY reason to reject it is the resource budget (not bad structure).
    import shutil

    shutil.copy(src, dst)
    with zipfile.ZipFile(dst, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * size)
    return dst


def test_valid_epub_with_big_member_opens_without_budget(tmp_path, epub3_path):
    # Control: without a tightened budget the augmented book still opens, proving
    # the rejection below is the budget talking, not a structural defect.
    p = _valid_epub_with_big_member(epub3_path, tmp_path / "ok.epub", 8192)
    with Book.open(p) as book:
        assert book.spine


def test_zip_preflight_rejects_oversized_member(tmp_path, epub3_path, monkeypatch):
    monkeypatch.setattr(Book, "MAX_ENTRY_UNCOMPRESSED", 1024)
    p = _valid_epub_with_big_member(epub3_path, tmp_path / "bomb.epub", 8192)
    with pytest.raises(InvalidEpubError):
        Book.open(p)


def test_zip_preflight_rejects_excessive_total(tmp_path, epub3_path, monkeypatch):
    monkeypatch.setattr(Book, "MAX_TOTAL_UNCOMPRESSED", 1024)
    p = _valid_epub_with_big_member(epub3_path, tmp_path / "bomb.epub", 8192)
    with pytest.raises(InvalidEpubError):
        Book.open(p)


def test_read_cap_bounds_decompression(epub3_path):
    # Even past preflight, a single read is capped so a lying header can't
    # decompress unbounded.
    with Book.open(epub3_path) as book:
        book.MAX_ENTRY_UNCOMPRESSED = 4        # instance override, tiny cap
        with pytest.raises(InvalidEpubError):
            book.read_resource("OEBPS/ch1.xhtml")


# ---- progress carried to the frontend ------------------------------------- #
def test_rendered_section_carries_progress(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    session.report_progress(0.5)
    assert session.current_section().progress == 0.5


# ---- NaN / inf rejection -------------------------------------------------- #
def test_locator_rejects_non_finite_progress():
    assert Locator(0, float("nan")).progress == 0.0
    assert Locator(0, float("inf")).progress == 0.0
    assert Locator(0, float("-inf")).progress == 0.0


def test_settings_reject_non_finite():
    s = ReaderSettings(font_scale=float("nan"), line_height=float("inf")).clamped()
    assert math.isfinite(s.font_scale) and math.isfinite(s.line_height)


# ---- persistence: concurrent stores don't lose data ----------------------- #
def test_two_stores_do_not_lose_bookmarks(tmp_path, epub3_path):
    path = tmp_path / "state.json"
    a = ReaderSession(JsonProgressStore(path))
    b = ReaderSession(JsonProgressStore(path))
    a.open(epub3_path)
    b.open(epub3_path)
    a.add_bookmark("from A")
    b.report_progress(0.5)     # b writes its locator after a added a bookmark
    # A reader opening the file fresh must see both updates.
    fresh = JsonProgressStore(path)
    labels = [bm.label for bm in fresh.get_bookmarks(a.book.book_id)]
    assert "from A" in labels


# ---- corrupt / hostile state file ----------------------------------------- #
def test_state_file_wrong_root_type_does_not_brick(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("[]", encoding="utf-8")        # valid JSON, wrong shape
    store = JsonProgressStore(p)
    assert store.get_settings().theme == "obsidian"     # clean state, no crash
    # The damaged file is quarantined, not left to crash the next launch.
    assert list(tmp_path.glob("state.corrupt.*.json"))


def test_state_file_garbage_does_not_brick(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ not json", encoding="utf-8")
    store = JsonProgressStore(p)
    assert store.get_settings().theme == "obsidian"


# ---- 0.4 review: nested hostile JSON no longer crashes -------------------- #
def test_hostile_nested_locator_does_not_crash(tmp_path):
    import json

    p = tmp_path / "state.json"
    p.write_text(json.dumps({"locators": {"x": {"spine_index": "banana"}}}), encoding="utf-8")
    store = JsonProgressStore(p)
    loc = store.get_locator("x")            # coerced, not a crash
    assert loc is not None and loc.spine_index == 0


def test_hostile_nested_settings_does_not_crash(tmp_path):
    import json

    p = tmp_path / "state.json"
    p.write_text(json.dumps({"settings": {"theme": []}}), encoding="utf-8")
    store = JsonProgressStore(p)
    assert store.get_settings().theme == "obsidian"


# ---- 0.4 review: two sessions preserve both bookmarks --------------------- #
def test_two_sessions_keep_both_bookmarks(tmp_path, epub3_path):
    path = tmp_path / "state.json"
    a = ReaderSession(JsonProgressStore(path))
    b = ReaderSession(JsonProgressStore(path))
    a.open(epub3_path)
    b.open(epub3_path)
    a.add_bookmark("A")
    b.add_bookmark("B")     # b's cache was stale; must not erase A
    labels = sorted(bm.label for bm in JsonProgressStore(path).get_bookmarks(a.book.book_id))
    assert labels == ["A", "B"]


# ---- 0.4 review: book identity uses a content fingerprint ----------------- #
def test_same_identifier_different_content_differ(tmp_path, epub3_path):
    import shutil
    import zipfile

    other = tmp_path / "other.epub"
    shutil.copy(epub3_path, other)
    with zipfile.ZipFile(other, "a") as zf:
        zf.writestr("OEBPS/extra.txt", b"different content")   # same dc:identifier
    with Book.open(epub3_path) as a, Book.open(other) as b:
        assert a.book_id != b.book_id      # no cross-book progress merge


# ---- 0.4 review: archive preflight before ZipFile construction ------------ #
def test_archive_size_cap_rejects_before_open(tmp_path, epub3_path, monkeypatch):
    monkeypatch.setattr(Book, "MAX_ARCHIVE_BYTES", 10)   # smaller than any real epub
    with pytest.raises(InvalidEpubError):
        Book.open(epub3_path)


def test_declared_entry_count_preflight(tmp_path, epub3_path, monkeypatch):
    monkeypatch.setattr(Book, "MAX_FILE_COUNT", 1)       # fixture has several members
    with pytest.raises(InvalidEpubError):
        Book.open(epub3_path)


# ---- 0.4 review: search hit carries its ordinal --------------------------- #
def test_search_hit_carries_ordinal_to_section(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    seen = []
    session.on_section(seen.append)
    hits = session.search("Chapter")     # two hits, ordinals 0 then 0 per section
    # Fabricate a hit with ordinal 2 to prove the ordinal propagates verbatim.
    from epubreader.core.search import SearchHit

    hit = SearchHit(hits[0].spine_index, hits[0].key, "", "Chapter", "…", 0, 7, 2)
    session.go_to_search_hit(hit)
    assert seen[-1].highlight == "Chapter"
    assert seen[-1].highlight_ordinal == 2
    # One-shot: cleared on the next render.
    session.update_settings(ReaderSettings())
    assert seen[-1].highlight_ordinal == 0
