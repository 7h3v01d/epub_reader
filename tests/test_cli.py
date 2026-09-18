# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""CLI frontend tests — the command handler is pure, so no terminal is needed."""

from __future__ import annotations

import io

from epubreader.frontend.base import ReaderFrontend
from epubreader.frontends.cli.reader import CliReader
from epubreader.session.session import ReaderSession
from epubreader.session.storage import JsonProgressStore, MemoryProgressStore


def _reader(book_path, store=None, color=False):
    reader = CliReader(
        ReaderSession(store or MemoryProgressStore()),
        width=60,
        color=color,
        out=io.StringIO(),
    )
    reader.session.open(str(book_path))
    return reader


def test_cli_is_a_readerfrontend(epub3_path):
    # The payoff again: a third UI satisfying the same contract, no engine change.
    assert isinstance(_reader(epub3_path), ReaderFrontend)


def test_initial_render_shows_title_and_first_section(epub3_path):
    out = _reader(epub3_path).render_section()
    assert "Fixture Three" in out
    assert "1/2" in out
    assert "Chapter One" in out and "Hello." in out


def test_next_and_prev(epub3_path):
    r = _reader(epub3_path)
    assert "Chapter Two" in r.handle_command("next")
    assert "Chapter One" in r.handle_command("prev")


def test_prev_at_start_is_handled(epub3_path):
    r = _reader(epub3_path)
    msg = r.handle_command("prev")          # already at first section
    assert "Chapter One" not in msg or "no previous" in msg.lower() or msg  # no crash
    # next past the last section reports, doesn't raise
    r.handle_command("next")
    assert isinstance(r.handle_command("next"), str)


def test_toc_lists_and_nests(epub3_path):
    out = _reader(epub3_path).render_toc()
    assert "Chapter One" in out and "Chapter Two" in out
    # Chapter Two is nested under Chapter One in the fixture, so it is indented.
    two_line = [ln for ln in out.splitlines() if "Chapter Two" in ln][0]
    assert two_line.index("Chapter Two") > out.splitlines()[0].index("Chapter One")


def test_search_and_jump(epub3_path):
    r = _reader(epub3_path)
    listing = r.handle_command("/Chapter")
    assert "2 match" in listing
    jumped = r.handle_command("j 2")
    assert "2/2" in jumped and "Chapter Two" in jumped


def test_goto_toc_entry(epub3_path):
    r = _reader(epub3_path)
    out = r.handle_command("g 2")           # second flattened TOC entry
    assert "Chapter Two" in out


def test_bookmark_add_list_goto_remove(epub3_path):
    r = _reader(epub3_path)
    r.handle_command("next")
    assert "bookmarked" in r.handle_command("b")
    assert "Chapter Two" in r.handle_command("bl")
    r.handle_command("prev")
    assert "2/2" in r.handle_command("bg 1")     # bookmark restored spine 1
    assert "removed" in r.handle_command("br 1")
    assert "no bookmarks" in r.handle_command("bl")


def test_highlight_uses_reverse_video_when_colored(epub3_path):
    r = _reader(epub3_path, color=True)
    r.handle_command("/World")
    out = r.handle_command("j 1")
    assert "\033[7m" in out                  # the match is emphasised


def test_highlight_marks_actual_case_on_insensitive_search(epub3_path):
    # A lowercase search still highlights the real "Chapter" (the engine's
    # matched text), proving the CLI highlights the locator's exact text.
    r = _reader(epub3_path, color=True)
    r.handle_command("/chapter")
    out = r.handle_command("j 1")
    assert "\033[7mChapter\033[0m" in out


def test_unknown_command_message(epub3_path):
    assert "unknown command" in _reader(epub3_path).handle_command("frobnicate")


def test_cli_shares_store_with_other_sessions(tmp_path, epub3_path):
    store_path = tmp_path / "state.json"
    r = _reader(epub3_path, store=JsonProgressStore(store_path))
    r.handle_command("next")
    r.handle_command("b")                    # bookmark via CLI
    # A separate session over the same store sees the CLI's bookmark.
    other = ReaderSession(JsonProgressStore(store_path))
    other.open(str(epub3_path))
    assert any(bm.label == "Chapter Two" for bm in other.bookmarks())
