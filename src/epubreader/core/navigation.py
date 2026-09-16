# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Table-of-contents parsing for both EPUB3 nav documents and EPUB2 NCX.

Both formats collapse into the same :class:`NavPoint` tree so a frontend has
one shape to render regardless of the source book's era.
"""

from __future__ import annotations

from typing import Optional
from xml.etree import ElementTree as ET

from .models import NavPoint
from .paths import parent_dir, resolve_href

_XHTML_NS = "http://www.w3.org/1999/xhtml"
_EPUB_NS = "http://www.idpf.org/2007/ops"
_NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


# --------------------------------------------------------------------------- #
# EPUB 3 nav document (XHTML <nav epub:type="toc"> ... <ol><li><a>)
# --------------------------------------------------------------------------- #
def _parse_nav_list(ol_el: ET.Element, base_dir: str) -> tuple[NavPoint, ...]:
    points: list[NavPoint] = []
    for li in [c for c in ol_el if _local(c.tag) == "li"]:
        anchor = next((c for c in li.iter() if _local(c.tag) == "a"), None)
        label = ""
        key = ""
        fragment = ""
        if anchor is not None:
            label = "".join(anchor.itertext()).strip()
            href = anchor.get("href")
            if href:
                key, fragment = resolve_href(base_dir, href)
        child_ol = next((c for c in li if _local(c.tag) == "ol"), None)
        children = _parse_nav_list(child_ol, base_dir) if child_ol is not None else ()
        if label or key or children:
            points.append(NavPoint(label=label or "(untitled)", key=key,
                                   fragment=fragment, children=children))
    return tuple(points)


def parse_nav_document(nav_key: str, nav_xml: bytes) -> tuple[NavPoint, ...]:
    """Parse an EPUB3 nav document into the toc ``NavPoint`` tree."""
    root = ET.fromstring(nav_xml)
    base_dir = parent_dir(nav_key)

    def is_toc_nav(el: ET.Element) -> bool:
        if _local(el.tag) != "nav":
            return False
        etype = el.get(f"{{{_EPUB_NS}}}type") or el.get("type") or ""
        return "toc" in etype.split()

    toc_nav = next((el for el in root.iter() if is_toc_nav(el)), None)
    if toc_nav is None:
        # Fall back to the first <nav> that carries a list.
        toc_nav = next((el for el in root.iter() if _local(el.tag) == "nav"), None)
    if toc_nav is None:
        return ()
    ol = next((c for c in toc_nav.iter() if _local(c.tag) == "ol"), None)
    return _parse_nav_list(ol, base_dir) if ol is not None else ()


# --------------------------------------------------------------------------- #
# EPUB 2 NCX (<navMap><navPoint><navLabel><text>, <content src>)
# --------------------------------------------------------------------------- #
def _parse_navpoint(np_el: ET.Element, base_dir: str) -> Optional[NavPoint]:
    label_el = np_el.find(f"{{{_NCX_NS}}}navLabel/{{{_NCX_NS}}}text")
    content_el = np_el.find(f"{{{_NCX_NS}}}content")
    label = (label_el.text or "").strip() if label_el is not None else "(untitled)"
    key = ""
    fragment = ""
    if content_el is not None and content_el.get("src"):
        key, fragment = resolve_href(base_dir, content_el.get("src"))
    children = tuple(
        p for p in (
            _parse_navpoint(child, base_dir)
            for child in np_el.findall(f"{{{_NCX_NS}}}navPoint")
        ) if p is not None
    )
    return NavPoint(label=label, key=key, fragment=fragment, children=children)


def parse_ncx(ncx_key: str, ncx_xml: bytes) -> tuple[NavPoint, ...]:
    """Parse an EPUB2 NCX into the toc ``NavPoint`` tree."""
    root = ET.fromstring(ncx_xml)
    base_dir = parent_dir(ncx_key)
    nav_map = root.find(f"{{{_NCX_NS}}}navMap")
    if nav_map is None:
        return ()
    return tuple(
        p for p in (
            _parse_navpoint(np, base_dir)
            for np in nav_map.findall(f"{{{_NCX_NS}}}navPoint")
        ) if p is not None
    )
