# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Session behaviour: navigation, resume-from-store, progress, re-render."""

from __future__ import annotations

import pytest

from epubreader.core.exceptions import NavigationError
from epubreader.core.locators import Locator
from epubreader.render import inject_stylesheet, reader_stylesheet
from epubreader.session import (
    JsonProgressStore,
    MemoryProgressStore,
    ReaderSession,
    ReaderSettings,
)


def test_open_emits_first_section(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    seen = []
    session.on_section(seen.append)
    session.open(epub3_path)
    assert seen[-1].spine_index == 0
    assert seen[-1].key == "OEBPS/ch1.xhtml"
    assert seen[-1].is_first and not seen[-1].is_last


def test_next_and_prev(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    assert session.next_section() is True
    assert session.current_section().spine_index == 1
    assert session.current_section().is_last
    assert session.next_section() is False  # already at end
    assert session.prev_section() is True
    assert session.current_section().spine_index == 0
    assert session.prev_section() is False  # already at start


def test_go_to_nav_point_jumps_by_key(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    ch2 = session.toc()[0].children[0]
    session.go_to_nav_point(ch2)
    assert session.current_section().spine_index == 1
    assert session.current_section().fragment == "start"


def test_out_of_range_navigation_raises(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    with pytest.raises(NavigationError):
        session.go_to_spine(99)


def test_progress_persisted_and_resumed(epub3_path):
    store = MemoryProgressStore()
    session = ReaderSession(store)
    session.open(epub3_path)
    session.go_to_spine(1)
    session.report_progress(0.5)
    session.close()

    # Fresh session, same store -> resumes to spine 1 at 0.5.
    session2 = ReaderSession(store)
    session2.open(epub3_path)
    assert session2.locator().spine_index == 1
    assert session2.locator().progress == pytest.approx(0.5)


def test_resume_disabled_starts_at_zero(epub3_path):
    store = MemoryProgressStore()
    s1 = ReaderSession(store)
    s1.open(epub3_path)
    s1.go_to_spine(1)
    s1.close()
    s2 = ReaderSession(store)
    s2.open(epub3_path, resume=False)
    assert s2.locator().spine_index == 0


def test_settings_change_triggers_rerender(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    count = []
    session.on_section(lambda s: count.append(s))
    before = len(count)
    session.update_settings(ReaderSettings(font_scale=1.4))
    assert len(count) == before + 1


def test_book_opened_fires_once_before_first_section(epub3_path):
    # The book-scoped channel (metadata/TOC) must fire exactly once per book,
    # and before the first section, so chrome is built before content lands.
    session = ReaderSession(MemoryProgressStore())
    order = []
    session.on_book_opened(lambda: order.append("opened"))
    session.on_section(lambda s: order.append("section"))
    session.open(epub3_path)
    assert order == ["opened", "section"]


def test_settings_change_does_not_refire_book_opened(epub3_path):
    # A theme/scale change re-renders the section but must NOT re-fire the
    # book-opened channel, or the TOC tree would be cleared and rebuilt under
    # the user on every settings tweak (losing expansion/selection).
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    opened = []
    section = []
    session.on_book_opened(lambda: opened.append(1))
    session.on_section(lambda s: section.append(1))
    session.update_settings(ReaderSettings(font_scale=1.4))
    assert opened == []       # book chrome untouched
    assert section == [1]     # section re-rendered once


def test_navigation_does_not_refire_book_opened(epub3_path):
    # Page turns are section-scoped only.
    session = ReaderSession(MemoryProgressStore())
    session.open(epub3_path)
    opened = []
    session.on_book_opened(lambda: opened.append(1))
    session.next_section()
    session.prev_section()
    assert opened == []


def test_json_store_round_trip(tmp_path, epub3_path):
    store_path = tmp_path / "state.json"
    store = JsonProgressStore(store_path)
    session = ReaderSession(store)
    session.open(epub3_path)
    session.go_to_spine(1)
    session.close()
    assert store_path.is_file()

    reopened = JsonProgressStore(store_path)
    loc = reopened.get_locator("urn:uuid:epub3-fixture-0001")
    assert loc is not None and loc.spine_index == 1


def test_reader_stylesheet_carries_theme_tokens():
    css = reader_stylesheet(ReaderSettings(theme="obsidian"))
    assert "#0b0f14" in css   # obsidian bg token
    assert "#2fd6c3" in css   # teal link token


def test_inject_stylesheet_into_head():
    html = b"<html><head><title>x</title></head><body>hi</body></html>"
    out = inject_stylesheet(html, "application/xhtml+xml", "body{color:red}")
    assert b"<style" in out and out.index(b"<style") < out.index(b"</head>")


def test_inject_stylesheet_passes_non_html_through():
    png = b"\x89PNG\r\n"
    assert inject_stylesheet(png, "image/png", "x{}") == png


def test_locator_progress_clamped():
    assert Locator(spine_index=0, progress=5.0).progress == 1.0
    assert Locator(spine_index=0, progress=-1.0).progress == 0.0
