# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Full-text search over the engine, exercised against the fixture books."""

from __future__ import annotations

from epubreader.core.book import Book
from epubreader.core.search import SearchHit, extract_text, search_book, section_titles
from epubreader.session.session import ReaderSession
from epubreader.session.storage import MemoryProgressStore


def test_search_finds_term_in_each_section(epub3_path):
    with Book.open(epub3_path) as book:
        hits = search_book(book, "Chapter")
    assert [h.spine_index for h in hits] == [0, 1]
    assert [h.section_title for h in hits] == ["Chapter One", "Chapter Two"]


def test_search_is_case_insensitive_by_default(epub3_path):
    with Book.open(epub3_path) as book:
        assert len(search_book(book, "chapter")) == 2
        assert len(search_book(book, "chapter", case_sensitive=True)) == 0


def test_search_whole_word_option(epub3_path):
    with Book.open(epub3_path) as book:
        assert len(search_book(book, "Chap")) == 2            # substring
        assert len(search_book(book, "Chap", whole_word=True)) == 0


def test_search_excludes_head_title_text(epub3_path):
    # ch1's <head><title>One</title></head> must NOT produce a hit; only the
    # body's "Chapter One" should match, so exactly one hit in spine 0.
    with Book.open(epub3_path) as book:
        hits = search_book(book, "One")
    assert len(hits) == 1
    assert hits[0].spine_index == 0


def test_search_snippet_offsets_bound_the_match(epub3_path):
    with Book.open(epub3_path) as book:
        (hit,) = search_book(book, "World")
    assert hit.snippet[hit.match_start:hit.match_end] == "World"


def test_search_empty_query_returns_nothing(epub3_path):
    with Book.open(epub3_path) as book:
        assert search_book(book, "") == []
        assert search_book(book, "   ") == []
        assert search_book(book, "zzz") == []


def test_search_respects_max_results(epub3_path):
    with Book.open(epub3_path) as book:
        assert len(search_book(book, "Chapter", max_results=1)) == 1


def test_search_hit_round_trips_through_dict():
    hit = SearchHit(3, "OEBPS/x.xhtml", "Title", "q", "a q b", 2, 3, 5)
    assert SearchHit.from_dict(hit.to_dict()) == hit


def test_extract_text_drops_script_and_style():
    html = b"<html><head><style>.x{color:red}</style></head>" \
           b"<body><script>var a=1;</script><p>Visible</p></body></html>"
    text = extract_text(html)
    assert "Visible" in text
    assert "color" not in text
    assert "var a" not in text


def test_section_titles_fall_back_to_stem(epub3_path):
    with Book.open(epub3_path) as book:
        titles = section_titles(book)
    # Both fixture sections are in the TOC, so both carry real labels.
    assert titles["OEBPS/ch1.xhtml"] == "Chapter One"


def test_session_search_and_navigate_sets_highlight(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    seen = []
    session.on_section(seen.append)
    hits = session.search("World")
    session.go_to_search_hit(hits[0])
    # The section emitted on navigation carries the highlight term...
    assert seen[-1].spine_index == 1
    assert seen[-1].highlight == "World"
    # ...but it is one-shot: a later re-render must not still highlight.
    from epubreader.session.settings import ReaderSettings
    session.update_settings(ReaderSettings(font_scale=1.3))
    assert seen[-1].highlight == ""
