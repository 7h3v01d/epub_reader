# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Full-text search across a :class:`Book`.

This lives in the engine, not a frontend, so *every* UI gets search for free:
the Qt window, a future web server, and a CLI all call :func:`search_book` and
render the returned :class:`SearchHit` values however they like. A hit carries a
spine locator plus the matched text and a readable snippet — never a URL and
nothing toolkit-specific — so navigating to a hit is just ordinary session
navigation, and highlighting is left to the frontend (Qt's ``findText``, a
browser's find, …).

Text is extracted with the standard-library HTML parser, with ``<script>`` and
``<style>`` content excluded so their source never pollutes results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid a runtime import cycle; Book only needed for typing
    from .book import Book

# Media types whose bytes are worth searching as markup.
_TEXT_MEDIA = ("application/xhtml+xml", "text/html", "application/x-dtbook+xml")

# Tags whose textual content must never appear in results.
_SKIP_TAGS = {"script", "style", "head", "title"}

# Tags that imply a visual break, so adjacent words don't fuse on extraction.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre", "td",
}


@dataclass(frozen=True)
class SearchHit:
    """One match, located by spine index and described for a results list."""

    spine_index: int
    key: str
    section_title: str
    query: str
    snippet: str
    #: Offsets of the match *within* ``snippet`` (for the frontend to emphasise).
    match_start: int
    match_end: int
    #: 0-based index of this match within its section (lets a frontend step to
    #: the nth occurrence when highlighting).
    ordinal: int
    #: Search semantics used, so a renderer can locate the same occurrence
    #: (native find alone would count matches differently and mis-target).
    case_sensitive: bool = False
    whole_word: bool = False

    def to_dict(self) -> dict:
        return {
            "spine_index": self.spine_index,
            "key": self.key,
            "section_title": self.section_title,
            "query": self.query,
            "snippet": self.snippet,
            "match_start": self.match_start,
            "match_end": self.match_end,
            "ordinal": self.ordinal,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchHit":
        return cls(
            spine_index=int(data["spine_index"]),
            key=str(data["key"]),
            section_title=str(data.get("section_title", "")),
            query=str(data.get("query", "")),
            snippet=str(data.get("snippet", "")),
            match_start=int(data.get("match_start", 0)),
            match_end=int(data.get("match_end", 0)),
            ordinal=int(data.get("ordinal", 0)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            whole_word=bool(data.get("whole_word", False)),
        )


class _TextExtractor(HTMLParser):
    """Collect visible text, dropping script/style and breaking on block tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def extract_text(data: bytes, *, encoding: str = "utf-8") -> str:
    """Decode markup bytes and return their visible text content."""
    markup = data.decode(encoding, errors="replace")
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup shouldn't abort a search
        pass
    return parser.text()


def section_titles(book: "Book") -> dict[str, str]:
    """Map each spine key to the best human label from the table of contents.

    A frontend and the search UI both want a readable per-section title; the TOC
    is the natural source. Spine documents with no nav entry fall back to their
    file stem so a label is always available.
    """
    labels: dict[str, str] = {}
    for top in book.toc:
        for point in top.flatten():
            # First (usually shallowest) label wins for a given document.
            if point.key and point.key not in labels and point.label:
                labels[point.key] = point.label.strip()
    result: dict[str, str] = {}
    for item in book.spine:
        stem = item.key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        result[item.key] = labels.get(item.key, stem or item.key)
    return result


def _build_snippet(text: str, start: int, end: int, context: int) -> tuple[str, int, int]:
    """Return (snippet, match_start, match_end) with whitespace collapsed."""
    lo = max(0, start - context)
    hi = min(len(text), end + context)
    left = " ".join(text[lo:start].split())
    mid = " ".join(text[start:end].split())
    right = " ".join(text[end:hi].split())

    out = "… " if lo > 0 else ""
    if left:
        out += left + " "
    match_start = len(out)
    out += mid
    match_end = len(out)
    if right:
        out += " " + right
    if hi < len(text):
        out += " …"
    return out, match_start, match_end


def _compile(query: str, *, case_sensitive: bool, whole_word: bool) -> re.Pattern:
    pattern = re.escape(query)
    if whole_word:
        pattern = rf"\b{pattern}\b"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def search_book(
    book: "Book",
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    max_results: int = 200,
    context: int = 48,
) -> list[SearchHit]:
    """Search every spine document in reading order.

    Returns at most ``max_results`` hits. An empty or whitespace-only query
    yields no hits. Non-markup spine items (rare) are skipped.
    """
    if not query or not query.strip():
        return []

    regex = _compile(query, case_sensitive=case_sensitive, whole_word=whole_word)
    titles = section_titles(book)
    hits: list[SearchHit] = []

    for item in book.spine:
        if not any(item.media_type.startswith(m) for m in _TEXT_MEDIA):
            continue
        try:
            data = book.read_resource(item.key).data
        except Exception:  # noqa: BLE001 - a bad section shouldn't kill search
            continue
        text = extract_text(data)
        title = titles.get(item.key, item.key)

        for ordinal, match in enumerate(regex.finditer(text)):
            snippet, ms, me = _build_snippet(text, match.start(), match.end(), context)
            hits.append(
                SearchHit(
                    spine_index=item.index,
                    key=item.key,
                    section_title=title,
                    query=query,
                    snippet=snippet,
                    match_start=ms,
                    match_end=me,
                    ordinal=ordinal,
                    case_sensitive=case_sensitive,
                    whole_word=whole_word,
                )
            )
            if len(hits) >= max_results:
                return hits
    return hits
