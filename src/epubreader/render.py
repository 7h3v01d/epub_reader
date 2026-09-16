# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Shared, UI-agnostic content rendering.

Turning :class:`ReaderSettings` into a stylesheet and injecting it into a book's
XHTML lives here, not in any one frontend, so the Qt renderer and a future web
renderer produce byte-identical output. The colour tokens are the house design
system (Obsidian / Panel / Teal / Phosphor / Amber / Text).
"""

from __future__ import annotations

import re

from .session.settings import ReaderSettings

# House design-system tokens.
_TOKENS = {
    "obsidian": {"bg": "#0b0f14", "fg": "#c8d3da", "link": "#2fd6c3", "sel": "#11161d"},
    "sepia": {"bg": "#f4ecd8", "fg": "#3b352b", "link": "#9a6a2f", "sel": "#e8dcc0"},
    "light": {"bg": "#ffffff", "fg": "#1a1f24", "link": "#0a7f77", "sel": "#e6f4f2"},
}

_XHTML_MEDIA = {"application/xhtml+xml", "text/html", "application/html"}
_HEAD_CLOSE = re.compile(rb"</head\s*>", re.IGNORECASE)
_HTML_OPEN = re.compile(rb"<html[^>]*>", re.IGNORECASE)


def reader_stylesheet(settings: ReaderSettings) -> str:
    """CSS applied on top of the book's own styles for legibility + theme."""
    s = settings.clamped()
    t = _TOKENS.get(s.theme, _TOKENS["obsidian"])
    return f"""
/* epubreader injected theme — {s.theme} */
:root {{ color-scheme: {'dark' if s.theme == 'obsidian' else 'light'}; }}
html, body {{
  background: {t['bg']} !important;
  color: {t['fg']} !important;
  font-size: {s.font_scale * 100:.0f}% !important;
  line-height: {s.line_height} !important;
  margin: 0 !important;
}}
body {{
  padding: {s.margin_em}em max({s.margin_em}em, 6vw) !important;
  max-width: 44rem;
  margin: 0 auto !important;
  -webkit-text-size-adjust: 100%;
}}
a {{ color: {t['link']} !important; }}
::selection {{ background: {t['sel']}; }}
img, svg, video {{ max-width: 100% !important; height: auto !important; }}
pre, code {{ white-space: pre-wrap; word-wrap: break-word; }}
""".strip()


def inject_stylesheet(data: bytes, media_type: str, css: str) -> bytes:
    """Insert ``css`` into an (X)HTML document; pass other media through.

    The style is inserted just before ``</head>`` (or after ``<html>`` when no
    head is present) so it overrides book styles by document order.
    """
    base_media = media_type.split(";", 1)[0].strip().lower()
    if base_media not in _XHTML_MEDIA:
        return data
    style = f'<style type="text/css">{css}</style>'.encode("utf-8")
    if _HEAD_CLOSE.search(data):
        return _HEAD_CLOSE.sub(style + b"</head>", data, count=1)
    match = _HTML_OPEN.search(data)
    if match:
        head = b"<head>" + style + b"</head>"
        return data[: match.end()] + head + data[match.end():]
    return style + data
