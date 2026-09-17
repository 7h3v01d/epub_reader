# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The reading surface: a QWebEngineView wired to the ``epub`` scheme.

The view owns a private :class:`QWebEngineProfile` (off-the-record, so nothing
about the book is cached to disk), installs the scheme handler and the
deny-first interceptor on it, and renders a section by loading its
``epub://book/<key>`` URL. Scroll fraction is reported back to the session
without executing any page script, honouring the deny-first posture.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ...core.book import Book
from ...session.session import RenderedSection
from ...session.settings import ReaderSettings
from .page import ReaderPage
from .scheme import DenyFirstInterceptor, EpubSchemeHandler, url_for_key

# App-owned DOM search: rebuilds the engine's regex (escaped query, optional
# word boundaries, case flag), walks visible text nodes with a newline inserted
# between differing parents to approximate block breaks, then selects and scrolls
# to the Nth match. Runs in the application world, so it works with book-content
# JavaScript disabled. Placeholders are filled with json-safe values.
_HIGHLIGHT_JS = r"""(function(){
  var q=%(q)s, ordinal=%(n)d, caseSensitive=%(case)s, wholeWord=%(whole)s;
  var doc=document, root=doc.body||doc.documentElement;
  if(!root||!q) return;
  var BLOCK={P:1,DIV:1,BR:1,LI:1,TR:1,H1:1,H2:1,H3:1,H4:1,H5:1,H6:1,SECTION:1,ARTICLE:1,HEADER:1,FOOTER:1,BLOCKQUOTE:1,PRE:1,TD:1};
  function nb(n){ var e=n.parentNode; while(e&&e.nodeType===1){ if(BLOCK[e.nodeName]) return e; e=e.parentNode; } return null; }
  var pat=q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
  if(wholeWord) pat="\\b"+pat+"\\b";
  var re=new RegExp(pat, caseSensitive?"g":"gi");
  var w=doc.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes=[], text="", n, lb, first=true;
  while((n=w.nextNode())){
    var p=n.parentNode;
    if(p&&/^(SCRIPT|STYLE)$/.test(p.nodeName)) continue;
    var b=nb(n);
    if(!first&&b!==lb) text+="\n";
    first=false;
    nodes.push({node:n,start:text.length}); text+=n.nodeValue; lb=b;
  }
  var m, c=0, t=null;
  while((m=re.exec(text))){ if(c===ordinal){t={s:m.index,e:m.index+m[0].length};break;} c++; if(m.index===re.lastIndex) re.lastIndex++; }
  if(!t) return;
  function loc(a){ for(var i=nodes.length-1;i>=0;i--){ if(a>=nodes[i].start&&a-nodes[i].start<=nodes[i].node.nodeValue.length) return {node:nodes[i].node,offset:a-nodes[i].start}; } return null; }
  var s=loc(t.s), e=loc(t.e); if(!s||!e) return;
  var r=doc.createRange();
  try{ r.setStart(s.node,s.offset); r.setEnd(e.node,e.offset); }catch(_e){ return; }
  var sel=window.getSelection(); if(sel){ sel.removeAllRanges(); sel.addRange(r); }
  var rect=r.getBoundingClientRect();
  window.scrollTo(0,(window.scrollY||0)+rect.top-window.innerHeight/3);
})();"""


class ReaderView(QWebEngineView):
    """Renders book sections and reports reading progress."""

    progress_changed = pyqtSignal(float)
    external_link_requested = pyqtSignal(QUrl)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profile = QWebEngineProfile(self)  # off-the-record (no name)
        self._handler = EpubSchemeHandler(self)
        self._interceptor = DenyFirstInterceptor(self)
        self._profile.installUrlSchemeHandler(b"epub", self._handler)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = ReaderPage(self._profile, self)
        self._page.external_link_requested.connect(self.external_link_requested)
        self.setPage(self._page)
        self._page.scrollPositionChanged.connect(self._on_scroll)

        # Term to highlight once the next section finishes loading (from a
        # search hit). findText needs no page scripting, so it keeps the
        # deny-first posture intact.
        self._pending_find = ""
        self._pending_ordinal = 0
        self._pending_case = False
        self._pending_whole = False
        self._pending_progress = 0.0
        self.loadFinished.connect(self._on_load_finished)

    # ---- configuration --------------------------------------------------- #
    def set_book(self, book: Optional[Book]) -> None:
        self._handler.set_book(book)

    def apply_settings(self, settings: ReaderSettings) -> None:
        self._handler.set_settings(settings)
        self._page.apply_settings(settings)

    # ---- rendering ------------------------------------------------------- #
    def show_section(self, section: RenderedSection) -> None:
        self._pending_find = section.highlight
        self._pending_ordinal = section.highlight_ordinal
        self._pending_case = section.highlight_case
        self._pending_whole = section.highlight_whole_word
        # A fragment target wins over a stored fraction; otherwise restore the
        # saved reading position within the section.
        self._pending_progress = 0.0 if section.fragment else section.progress
        self.load(url_for_key(section.key, section.fragment))

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        if self._pending_find:
            self._highlight_occurrence(
                self._pending_find, self._pending_ordinal,
                self._pending_case, self._pending_whole,
            )
        elif self._pending_progress > 0:
            self._restore_scroll(self._pending_progress)
        self._pending_progress = 0.0

    def _highlight_occurrence(self, query: str, ordinal: int, case: bool, whole: bool) -> None:
        # App-owned DOM search in the application world (runs with book-content
        # JS disabled), using the engine's own regex semantics so the ordinal
        # targets the same occurrence the engine counted.
        import json

        script = _HIGHLIGHT_JS % {
            "q": json.dumps(query),
            "n": int(ordinal),
            "case": "true" if case else "false",
            "whole": "true" if whole else "false",
        }
        self._page.runJavaScript(script, QWebEngineScript.ScriptWorldId.ApplicationWorld)

    def _restore_scroll(self, fraction: float) -> None:
        # Scroll via an application-world script: this is app-initiated, so it
        # runs even though book-content JavaScript is disabled — book scripts
        # stay blocked, the deny-first posture is preserved.
        frac = max(0.0, min(1.0, fraction))
        script = (
            "(function(){var e=document.scrollingElement||document.documentElement;"
            "var m=e.scrollHeight-window.innerHeight;"
            f"if(m>0){{window.scrollTo(0,m*{frac});}}}})();"
        )
        self._page.runJavaScript(script, QWebEngineScript.ScriptWorldId.ApplicationWorld)

    # ---- progress (no page scripting required) --------------------------- #
    def _on_scroll(self, *_: object) -> None:
        pos = self._page.scrollPosition()
        contents = self._page.contentsSize()
        viewport = float(self.height())
        scrollable = max(1.0, contents.height() - viewport)
        fraction = pos.y() / scrollable if scrollable > 0 else 0.0
        self.progress_changed.emit(max(0.0, min(1.0, fraction)))
