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


# ---- 0.6 review: lying-EOCD count can't force ZipFile allocation --------- #
def test_lying_eocd_rejected_before_zipfile(tmp_path, monkeypatch):
    import struct
    import zipfile

    p = tmp_path / "many.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("META-INF/container.xml", b"<x/>")
        for i in range(Book.MAX_FILE_COUNT + 10):
            zf.writestr(f"f{i}.txt", b"")
    raw = bytearray(p.read_bytes())
    idx = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<H", raw, idx + 8, 1)     # entries this disk -> lie
    struct.pack_into("<H", raw, idx + 10, 1)    # total entries -> lie
    p.write_bytes(raw)

    import epubreader.core.book as book_mod

    def _boom(*a, **k):
        raise AssertionError("ZipFile constructed despite the CD preflight")

    monkeypatch.setattr(book_mod.zipfile, "ZipFile", _boom)
    with pytest.raises(InvalidEpubError):
        Book.open(p)                            # rejected by CD walk, no ZipFile


# ---- 0.6 review: oversized dc:identifier can't bloat the storage key ------ #
def test_oversized_identifier_yields_small_book_id(tmp_path, epub3_path):
    import re
    import zipfile

    with zipfile.ZipFile(epub3_path) as z:
        data = {n: z.read(n) for n in z.namelist()}
    opf = next(n for n in data if n.endswith(".opf"))
    huge = b"<dc:identifier>" + b"X" * (2 * 1024 * 1024) + b"</dc:identifier>"
    data[opf] = re.sub(rb"<dc:identifier[^>]*>.*?</dc:identifier>", huge, data[opf], count=1)
    p = tmp_path / "big.epub"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
        for n, c in data.items():
            z.writestr(n, c)
    with Book.open(p) as book:
        assert len(book.book_id) < 80          # fixed-size, not 2 MB


# ---- 0.6 review: scroll persistence is throttled -------------------------- #
def test_progress_persistence_is_throttled(epub3_path):
    class Counting(MemoryProgressStore):
        def __init__(self):
            super().__init__()
            self.writes = 0

        def set_locator(self, book_id, locator):
            self.writes += 1
            super().set_locator(book_id, locator)

    store = Counting()
    session = ReaderSession(store)
    session.open(epub3_path)
    base = store.writes
    session.report_progress(0.1)
    session.report_progress(0.2)
    session.report_progress(0.3)
    assert store.writes - base <= 1            # rapid scrolls collapse to one
    session.close()
    assert store.writes - base >= 1            # but the latest is flushed


# ---- 0.6 review: live session sees another session's new bookmark --------- #
def test_live_session_refreshes_bookmarks(tmp_path, epub3_path):
    sp = tmp_path / "state.json"
    a = ReaderSession(JsonProgressStore(sp))
    b = ReaderSession(JsonProgressStore(sp))
    a.open(epub3_path)
    b.open(epub3_path)
    a.add_bookmark("from A")
    assert "from A" in [bm.label for bm in b.bookmarks()]


# ---- 0.6 review: missing spine resource is rejected at open --------------- #
def test_missing_spine_resource_rejected(tmp_path):
    import zipfile

    p = tmp_path / "missing.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns='
            '"urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="id">X</dc:identifier><dc:title>T</dc:title></metadata>'
            '<manifest><item id="c" href="missing.xhtml" '
            'media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c"/></spine></package>',
        )
    with pytest.raises(InvalidEpubError):
        Book.open(p)


# ---- 0.5 review: scroll supersedes a stale anchor ------------------------ #
def test_scroll_clears_fragment_so_progress_restores(tmp_path, epub3_path):
    sp = tmp_path / "state.json"
    first = ReaderSession(JsonProgressStore(sp))
    first.open(epub3_path)
    key = first.current_section().key
    first.go_to_key(key, fragment="top")   # anchor navigation
    first.report_progress(0.8)             # then the user scrolls
    first.close()

    second = ReaderSession(JsonProgressStore(sp))
    second.open(epub3_path)
    section = second.current_section()
    # The stale anchor must not override the restored scroll position.
    assert section.fragment == ""
    assert section.progress == 0.8


# ---- 0.5 review: malformed bookmark value doesn't crash mutation --------- #
def test_add_bookmark_over_malformed_value_recovers(tmp_path):
    import json

    from epubreader.core.locators import Bookmark, Locator

    p = tmp_path / "state.json"
    p.write_text(json.dumps({"bookmarks": {"BID": {"not": "a-list"}}}), encoding="utf-8")
    store = JsonProgressStore(p)
    bm = Bookmark(id="x", locator=Locator(0), label="x", created_at="t")
    result = store.add_bookmark("BID", bm)     # must not raise
    assert [b.id for b in result] == ["x"]


# ---- 0.5 review: accepted-hosts separates bind address from Host --------- #
def test_accepted_hosts_specific_and_wildcard():
    from epubreader.frontends.web.frontend import accepted_hosts

    specific = accepted_hosts("192.168.1.50")
    assert "192.168.1.50" in specific and "127.0.0.1" in specific
    wildcard = accepted_hosts("0.0.0.0")
    # A wildcard bind must still accept loopback (and, best-effort, the machine's
    # own addresses) rather than only the literal 0.0.0.0.
    assert "127.0.0.1" in wildcard


# ---- 0.5 review: search hit carries its search semantics ----------------- #
def test_search_flags_reach_the_section(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    seen = []
    session.on_section(seen.append)
    hits = session.search("Chapter", whole_word=True, case_sensitive=True)
    session.go_to_search_hit(hits[0])
    assert seen[-1].highlight_whole_word is True
    assert seen[-1].highlight_case is True


# ---- engine-owned literal search locator --------------------------------- #
def test_locator_round_trips_against_engine_text(epub3_path):
    from epubreader.core.book import Book
    from epubreader.core.search import extract_text, find_literal, search_book

    with Book.open(epub3_path) as book:
        hits = search_book(book, "Chapter")
        assert hits
        for hit in hits:
            text = extract_text(book.read_resource(hit.key).data)
            start = find_literal(text, hit.prefix, hit.matched_text, hit.locator_ordinal)
            assert start >= 0
            assert text[start:start + len(hit.matched_text)] == hit.matched_text


def test_locator_is_newline_invariant(epub3_path):
    # A frontend that inserts block breaks differently still finds the same
    # match: the locator is newline-free, so removing every break can neither add
    # nor remove occurrences of it.
    from epubreader.core.book import Book
    from epubreader.core.search import extract_text, find_literal, search_book

    with Book.open(epub3_path) as book:
        hit = search_book(book, "World")[0]
        text = extract_text(book.read_resource(hit.key).data)
        mangled = text.replace("\n", "")            # extreme: no breaks at all
        a = find_literal(text, hit.prefix, hit.matched_text, hit.locator_ordinal)
        b = find_literal(mangled, hit.prefix, hit.matched_text, hit.locator_ordinal)
        assert a >= 0 and b >= 0
        assert text[a:a + len(hit.matched_text)] == hit.matched_text
        assert mangled[b:b + len(hit.matched_text)] == hit.matched_text


def test_locator_matched_text_preserves_actual_case(epub3_path):
    # A case-insensitive search for "chapter" matches "Chapter"; the locator
    # carries the ACTUAL text found, so a frontend's literal find can't miss it.
    from epubreader.core.book import Book
    from epubreader.core.search import search_book

    with Book.open(epub3_path) as book:
        hit = search_book(book, "chapter")[0]
        assert hit.matched_text == "Chapter"


# ---- 0.4 review: search hit's locator reaches the section ----------------- #
def test_search_hit_carries_locator_to_section(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    seen = []
    session.on_section(seen.append)
    from epubreader.core.search import SearchHit

    # A hit whose literal locator is (prefix="a ", matched="Cat", ordinal=2).
    hit = SearchHit(
        spine_index=session.current_section().spine_index,
        key=session.current_section().key,
        section_title="", query="cat", snippet="…", match_start=0, match_end=3,
        ordinal=0, matched_text="Cat", prefix="a ", locator_ordinal=2,
    )
    session.go_to_search_hit(hit)
    assert seen[-1].highlight == "Cat"            # the exact matched text
    assert seen[-1].highlight_prefix == "a "
    assert seen[-1].highlight_ordinal == 2        # the literal-locator ordinal
    # One-shot: cleared on the next render.
    session.update_settings(ReaderSettings())
    assert seen[-1].highlight_ordinal == 0 and seen[-1].highlight_prefix == ""
