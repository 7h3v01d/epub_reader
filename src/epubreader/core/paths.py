# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Href / archive-path resolution helpers.

EPUB hrefs are IRIs resolved relative to the file that contains them (the OPF,
or a NAV/NCX document). Archive entries, by contrast, are literal zip names.
This module bridges the two: it turns a ``(base_dir, href)`` pair into a
canonical archive *key* — posix, no leading slash, percent decoded, ``..``
segments collapsed — and can split off a trailing ``#fragment``.
"""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit


def split_fragment(href: str) -> tuple[str, str]:
    """Return ``(path, fragment)``; ``fragment`` has no leading ``#``."""
    parts = urlsplit(href)
    return parts.path, parts.fragment


def is_external(href: str) -> bool:
    """True if the href points outside the archive (has a network scheme)."""
    scheme = urlsplit(href).scheme.lower()
    return scheme in {"http", "https", "ftp", "mailto", "data", "tel"}


def canonical_key(path: str) -> str:
    """Normalise a raw (possibly percent-encoded) archive path to a key."""
    decoded = unquote(path)
    decoded = decoded.replace("\\", "/").lstrip("/")
    # posix.normpath collapses '..' and '.' without touching the filesystem.
    normed = posixpath.normpath(decoded)
    return "" if normed == "." else normed


def resolve_href(base_dir: str, href: str) -> tuple[str, str]:
    """Resolve ``href`` against ``base_dir`` → ``(key, fragment)``.

    ``base_dir`` is the directory of the referencing document as an archive
    key (e.g. ``"OEBPS"``). External hrefs are returned decoded but otherwise
    untouched with an empty fragment so callers can detect and refuse them.
    """
    if is_external(href):
        return href, ""
    path, fragment = split_fragment(href)
    if not path:
        # Pure in-document anchor (e.g. "#chapter") — same document.
        return "", fragment
    joined = posixpath.join(base_dir, unquote(path)) if base_dir else unquote(path)
    return canonical_key(joined), fragment


def parent_dir(key: str) -> str:
    """Directory portion of an archive key (``"OEBPS/x.opf"`` → ``"OEBPS"``)."""
    return posixpath.dirname(key)
