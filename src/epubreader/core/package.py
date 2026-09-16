# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Parser for the OPF package document (metadata, manifest, spine).

Handles both EPUB 2 and EPUB 3 conventions: EPUB2 declares its cover via a
``<meta name="cover" content="item-id"/>`` element and its TOC via the spine's
``toc`` attribute (an NCX); EPUB3 uses manifest ``properties`` (``nav``,
``cover-image``). Both are resolved here so downstream code needn't care.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET

from .exceptions import InvalidEpubError
from .models import ManifestItem, Metadata, SpineItem
from .paths import parent_dir, resolve_href

_OPF_NS = "http://www.idpf.org/2007/opf"
_DC_NS = "http://purl.org/dc/elements/1.1/"


@dataclass(frozen=True)
class Package:
    """Fully parsed OPF: where it lives plus its three sections."""

    opf_key: str
    content_dir: str
    metadata: Metadata
    manifest: dict[str, ManifestItem]  # keyed by item id
    spine: tuple[SpineItem, ...]
    # Archive key of the NCX declared by the spine's ``toc`` attr (EPUB2).
    ncx_key: Optional[str]

    def nav_item(self) -> Optional[ManifestItem]:
        """The EPUB3 navigation document, if the manifest declares one."""
        return next((i for i in self.manifest.values() if i.is_nav), None)


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_metadata(meta_el: Optional[ET.Element], manifest: dict[str, ManifestItem]) -> Metadata:
    if meta_el is None:
        return Metadata()

    creators = tuple(
        _text(el) for el in meta_el.findall(f"{{{_DC_NS}}}creator") if _text(el)
    )
    extra: dict[str, str] = {}
    for el in meta_el:
        if el.tag.startswith(f"{{{_DC_NS}}}"):
            name = el.tag.split("}", 1)[1]
            if name not in {"title", "creator", "language", "identifier",
                            "publisher", "description", "rights"} and _text(el):
                extra.setdefault(name, _text(el))

    # Cover resolution: EPUB2 <meta name="cover" content="cover-id"/>.
    cover_key: Optional[str] = None
    for meta in meta_el.findall(f"{{{_OPF_NS}}}meta"):
        if meta.get("name") == "cover":
            ref = meta.get("content")
            if ref and ref in manifest:
                cover_key = manifest[ref].key
                break
    # EPUB3 cover-image property wins if present.
    for item in manifest.values():
        if item.is_cover_image:
            cover_key = item.key
            break

    return Metadata(
        identifier=_text(meta_el.find(f"{{{_DC_NS}}}identifier")),
        title=_text(meta_el.find(f"{{{_DC_NS}}}title")) or "Untitled",
        language=_text(meta_el.find(f"{{{_DC_NS}}}language")),
        creators=creators,
        publisher=_text(meta_el.find(f"{{{_DC_NS}}}publisher")),
        description=_text(meta_el.find(f"{{{_DC_NS}}}description")),
        rights=_text(meta_el.find(f"{{{_DC_NS}}}rights")),
        cover_key=cover_key,
        extra=extra,
    )


def _parse_manifest(man_el: Optional[ET.Element], content_dir: str) -> dict[str, ManifestItem]:
    if man_el is None:
        raise InvalidEpubError("OPF has no <manifest>")
    items: dict[str, ManifestItem] = {}
    for el in man_el.findall(f"{{{_OPF_NS}}}item"):
        item_id = el.get("id")
        href = el.get("href")
        if not item_id or not href:
            continue
        key, _ = resolve_href(content_dir, href)
        props = frozenset(p for p in (el.get("properties") or "").split() if p)
        items[item_id] = ManifestItem(
            item_id=item_id,
            key=key,
            media_type=el.get("media-type") or "application/octet-stream",
            properties=props,
        )
    if not items:
        raise InvalidEpubError("OPF manifest declares no items")
    return items


def _parse_spine(
    spine_el: Optional[ET.Element], manifest: dict[str, ManifestItem]
) -> tuple[tuple[SpineItem, ...], Optional[str]]:
    if spine_el is None:
        raise InvalidEpubError("OPF has no <spine>")
    ncx_key: Optional[str] = None
    toc_id = spine_el.get("toc")
    if toc_id and toc_id in manifest:
        ncx_key = manifest[toc_id].key

    spine: list[SpineItem] = []
    index = 0
    for el in spine_el.findall(f"{{{_OPF_NS}}}itemref"):
        idref = el.get("idref")
        if not idref or idref not in manifest:
            continue
        spine.append(
            SpineItem(
                index=index,
                item=manifest[idref],
                linear=(el.get("linear", "yes").lower() != "no"),
            )
        )
        index += 1
    if not spine:
        raise InvalidEpubError("OPF spine has no resolvable itemrefs")
    return tuple(spine), ncx_key


def parse_package(opf_key: str, opf_xml: bytes) -> Package:
    """Parse OPF bytes located at ``opf_key`` into a :class:`Package`."""
    try:
        root = ET.fromstring(opf_xml)
    except ET.ParseError as exc:
        raise InvalidEpubError(f"OPF is not well-formed: {exc}") from exc

    content_dir = parent_dir(opf_key)
    manifest = _parse_manifest(root.find(f"{{{_OPF_NS}}}manifest"), content_dir)
    metadata = _parse_metadata(root.find(f"{{{_OPF_NS}}}metadata"), manifest)
    spine, ncx_key = _parse_spine(root.find(f"{{{_OPF_NS}}}spine"), manifest)
    return Package(
        opf_key=opf_key,
        content_dir=content_dir,
        metadata=metadata,
        manifest=manifest,
        spine=spine,
        ncx_key=ncx_key,
    )
