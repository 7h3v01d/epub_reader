# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Plain data models describing the structure of an opened EPUB.

These are deliberately framework-free dataclasses. The engine produces them;
any frontend (Qt, web, CLI) consumes them. Nothing here imports a UI toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Metadata:
    """Dublin Core metadata drawn from the OPF ``<metadata>`` element."""

    identifier: str = ""
    title: str = "Untitled"
    language: str = ""
    creators: tuple[str, ...] = ()
    publisher: str = ""
    description: str = ""
    rights: str = ""
    # Canonical archive key of the cover image, if one was declared.
    cover_key: Optional[str] = None
    # Raw dc:* extras that don't have a dedicated field, kept for frontends.
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestItem:
    """A single ``<item>`` from the OPF manifest.

    ``key`` is the canonical archive path (posix, no leading slash, percent
    decoded) — the value a frontend hands back to :meth:`Book.read_resource`.
    """

    item_id: str
    key: str
    media_type: str
    properties: frozenset[str] = frozenset()

    @property
    def is_nav(self) -> bool:
        return "nav" in self.properties

    @property
    def is_cover_image(self) -> bool:
        return "cover-image" in self.properties


@dataclass(frozen=True)
class SpineItem:
    """A reading-order entry (``<itemref>``) resolved to its manifest item."""

    index: int
    item: ManifestItem
    linear: bool = True

    @property
    def key(self) -> str:
        return self.item.key

    @property
    def media_type(self) -> str:
        return self.item.media_type


@dataclass(frozen=True)
class NavPoint:
    """A table-of-contents entry. ``children`` allows nested navigation."""

    label: str
    # Canonical archive key of the target document (fragment stripped).
    key: str
    # Optional in-document anchor, without the leading '#'.
    fragment: str = ""
    children: tuple["NavPoint", ...] = ()

    def flatten(self) -> list["NavPoint"]:
        """Depth-first list of this point and all descendants."""
        out = [self]
        for child in self.children:
            out.extend(child.flatten())
        return out


@dataclass(frozen=True)
class Resource:
    """Raw bytes plus media type for a single archive entry."""

    key: str
    data: bytes
    media_type: str
