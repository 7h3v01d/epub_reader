# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""A terminal frontend — the third UI on the same engine.

Like the Qt and web frontends, this subclasses :class:`ReaderFrontend` and drives
the same :class:`ReaderSession`; nothing in ``core`` or ``session`` changes. Its
``key -> transport`` mapping is the simplest of the three: read
``session.book.read_resource(key)`` and turn the bytes into plain text with the
engine's own :func:`extract_text`. Reusing that extractor means the CLI counts
search matches exactly as the engine does, so highlighting is byte-exact here.

The command handling is a pure function (``handle_command`` returns a string), so
it is fully testable without a terminal; :meth:`run` only wires stdin/stdout to
it.
"""

from __future__ import annotations

import shutil
import sys
import textwrap
from typing import Optional

from ...core.exceptions import EpubError, NavigationError
from ...core.models import Metadata, NavPoint
from ...core.search import SearchHit, extract_text
from ...frontend.base import ReaderFrontend
from ...session.session import ReaderSession, RenderedSection

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_REVERSE = "\033[7m"

_HELP = """\
commands:
  n, next           next section            p, prev        previous section
  t, toc            table of contents       g <n>          go to TOC entry n
  /<text>, s <text> search the book         j <n>          jump to search hit n
  b                 bookmark this spot       bl             list bookmarks
  bg <n>            go to bookmark n         br <n>         remove bookmark n
  h, help           this help                q, quit        quit"""


class CliReader(ReaderFrontend):
    """Presents a :class:`ReaderSession` in the terminal."""

    def __init__(
        self,
        session: ReaderSession,
        *,
        width: Optional[int] = None,
        color: Optional[bool] = None,
        out=None,
    ) -> None:
        super().__init__()
        self.bind_session(session)
        self._section: Optional[RenderedSection] = None
        self._toc: tuple[NavPoint, ...] = ()
        self._metadata: Optional[Metadata] = None
        self._error: str = ""
        self._last_hits: list[SearchHit] = []
        self._width = width
        self._out = out if out is not None else sys.stdout
        self._color = sys.stdout.isatty() if color is None else color

    # ---- ReaderFrontend contract: cache into a view-model ---------------- #
    def display_section(self, section: RenderedSection) -> None:
        self._section = section

    def display_toc(self, toc: tuple[NavPoint, ...]) -> None:
        self._toc = toc

    def display_metadata(self, metadata: Metadata) -> None:
        self._metadata = metadata

    def report_error(self, message: str) -> None:
        self._error = message

    def run(self) -> int:
        self._emit(self.render_section())
        while True:
            try:
                line = input("\nepub> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._emit("")
                break
            if line in ("q", "quit", "exit"):
                break
            output = self.handle_command(line)
            if output:
                self._emit(output)
        self.session.close()
        return 0

    # ---- command handling (pure; returns text to show) ------------------- #
    def handle_command(self, line: str) -> str:
        line = line.strip()
        if line.startswith("/"):
            return self._search(line[1:].strip())
        if not line or line in ("n", "next"):
            return self._nav(self.session.next_section)
        if line in ("p", "prev", "previous"):
            return self._nav(self.session.prev_section)
        if line in ("t", "toc", "contents"):
            return self.render_toc()
        if line in ("b", "bookmark"):
            return self._add_bookmark()
        if line in ("bl", "bookmarks"):
            return self.render_bookmarks()
        if line in ("h", "help", "?"):
            return _HELP

        parts = line.split(None, 1)
        cmd, arg = parts[0], (parts[1] if len(parts) > 1 else "")
        if cmd in ("s", "search"):
            return self._search(arg)
        if cmd in ("g", "goto"):
            return self._goto_toc(arg)
        if cmd in ("j", "jump"):
            return self._jump(arg)
        if cmd == "bg":
            return self._goto_bookmark(arg)
        if cmd == "br":
            return self._remove_bookmark(arg)
        return f"unknown command: {line!r} (try 'help')"

    # ---- rendering ------------------------------------------------------- #
    def render_section(self) -> str:
        section = self._section
        if section is None:
            return "no book open"
        try:
            data = self.session.book.read_resource(section.key).data
        except EpubError as exc:
            return self._c(f"cannot read section: {exc}", _DIM)
        body = self._wrap(extract_text(data))
        if section.highlight:
            body = self._mark(body, section)
        header = self._c(self._header(section), _BOLD)
        return f"{header}\n{self._rule()}\n{body}"

    def render_toc(self) -> str:
        if not self._toc:
            return "(no table of contents)"
        lines = []
        for i, point in enumerate(self._flat_toc(), start=1):
            indent = "  " * point[1]
            lines.append(f"{i:>3}. {indent}{point[0].label}")
        return "\n".join(lines)

    def render_bookmarks(self) -> str:
        bookmarks = self.session.bookmarks()
        if not bookmarks:
            return "(no bookmarks)"
        return "\n".join(
            f"{i:>3}. {b.label}  {self._c('(§%d)' % (b.locator.spine_index + 1), _DIM)}"
            for i, b in enumerate(bookmarks, start=1)
        )

    # ---- command implementations ----------------------------------------- #
    def _nav(self, action) -> str:  # noqa: ANN001
        try:
            action()
        except NavigationError as exc:
            return str(exc)
        return self.render_section()

    def _search(self, query: str) -> str:
        query = query.strip()
        if not query:
            return "usage: /<text>  (or: search <text>)"
        self._last_hits = self.session.search(query)
        if not self._last_hits:
            return f"no matches for {query!r}"
        lines = [f"{len(self._last_hits)} match(es) — 'j <n>' to jump:"]
        for i, hit in enumerate(self._last_hits, start=1):
            lines.append(f"{i:>3}. {self._c(hit.section_title, _BOLD)}  {hit.snippet}")
        return "\n".join(lines)

    def _jump(self, arg: str) -> str:
        idx = self._index(arg, len(self._last_hits))
        if idx is None:
            return "usage: j <n>  (from the last search results)"
        try:
            self.session.go_to_search_hit(self._last_hits[idx])
        except NavigationError as exc:
            return str(exc)
        return self.render_section()

    def _goto_toc(self, arg: str) -> str:
        flat = self._flat_toc()
        idx = self._index(arg, len(flat))
        if idx is None:
            return "usage: g <n>  (see 'toc')"
        try:
            self.session.go_to_nav_point(flat[idx][0])
        except NavigationError as exc:
            return str(exc)
        return self.render_section()

    def _add_bookmark(self) -> str:
        bookmark = self.session.add_bookmark()
        return f"bookmarked: {bookmark.label}"

    def _goto_bookmark(self, arg: str) -> str:
        bookmarks = self.session.bookmarks()
        idx = self._index(arg, len(bookmarks))
        if idx is None:
            return "usage: bg <n>  (see 'bookmarks')"
        self.session.go_to_bookmark(bookmarks[idx])
        return self.render_section()

    def _remove_bookmark(self, arg: str) -> str:
        bookmarks = self.session.bookmarks()
        idx = self._index(arg, len(bookmarks))
        if idx is None:
            return "usage: br <n>  (see 'bookmarks')"
        self.session.remove_bookmark(bookmarks[idx])
        return f"removed bookmark {idx + 1}"

    # ---- helpers --------------------------------------------------------- #
    def _header(self, section: RenderedSection) -> str:
        title = self._metadata.title if self._metadata else "?"
        pos = f"{section.spine_index + 1}/{section.total_sections}"
        pct = f"{round(section.progress * 100)}%" if section.progress else ""
        tail = f"  ·  {pct}" if pct else ""
        return f"{title}  —  {pos}{tail}"

    def _flat_toc(self) -> list[tuple[NavPoint, int]]:
        out: list[tuple[NavPoint, int]] = []

        def walk(points, depth):
            for p in points:
                out.append((p, depth))
                walk(p.children, depth + 1)

        walk(self._toc, 0)
        return out

    def _term_width(self) -> int:
        if self._width:
            return self._width
        return max(40, min(100, shutil.get_terminal_size((80, 24)).columns))

    def _rule(self) -> str:
        return self._c("─" * self._term_width(), _DIM)

    def _wrap(self, text: str) -> str:
        width = self._term_width()
        paragraphs = [seg.strip() for seg in text.split("\n")]
        wrapped = [textwrap.fill(p, width=width) for p in paragraphs if p]
        return "\n\n".join(wrapped) if wrapped else "(empty section)"

    def _mark(self, body: str, section: RenderedSection) -> str:
        # section.highlight is the exact matched text the engine found, so a
        # literal highlight is exact — no regex or case/word semantics needed.
        if not self._color or not section.highlight:
            return body
        return body.replace(
            section.highlight, f"{_REVERSE}{section.highlight}{_RESET}"
        )

    def _index(self, arg: str, length: int) -> Optional[int]:
        arg = arg.strip()
        if not arg.isdigit():
            return None
        n = int(arg) - 1
        return n if 0 <= n < length else None

    def _c(self, text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if self._color else text

    def _emit(self, text: str) -> None:
        print(text, file=self._out)
