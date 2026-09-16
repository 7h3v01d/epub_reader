# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Href/path resolution: the trickiest low-level logic, tested in isolation."""

from __future__ import annotations

from epubreader.core import paths


def test_split_fragment():
    assert paths.split_fragment("ch1.xhtml#top") == ("ch1.xhtml", "top")
    assert paths.split_fragment("ch1.xhtml") == ("ch1.xhtml", "")


def test_canonical_key_collapses_dotdot_and_decodes():
    assert paths.canonical_key("OEBPS/../OEBPS/a.xhtml") == "OEBPS/a.xhtml"
    assert paths.canonical_key("/OEBPS/pixel%20one.png") == "OEBPS/pixel one.png"


def test_resolve_href_relative_to_base_dir():
    key, frag = paths.resolve_href("OEBPS", "images/pixel%20one.png")
    assert key == "OEBPS/images/pixel one.png"
    assert frag == ""


def test_resolve_href_with_fragment():
    key, frag = paths.resolve_href("OEBPS", "ch2.xhtml#start")
    assert key == "OEBPS/ch2.xhtml"
    assert frag == "start"


def test_resolve_href_parent_traversal():
    key, _ = paths.resolve_href("OEBPS/text", "../images/c.png")
    assert key == "OEBPS/images/c.png"


def test_pure_anchor_stays_in_document():
    key, frag = paths.resolve_href("OEBPS", "#section")
    assert key == ""
    assert frag == "section"


def test_external_hrefs_detected():
    assert paths.is_external("https://example.com/x")
    assert paths.is_external("mailto:a@b.c")
    assert not paths.is_external("ch1.xhtml")
    ext_key, _ = paths.resolve_href("OEBPS", "https://example.com/x")
    assert ext_key.startswith("https://")
