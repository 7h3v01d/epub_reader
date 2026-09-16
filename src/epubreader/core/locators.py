# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""A portable reading-position model.

Full EPUB CFI is intentionally out of scope: it is brittle and frontend
specific. A :class:`Locator` instead pins a position to the spine index plus a
0..1 scroll fraction within that document, with an optional anchor fragment.
This is enough to resume a book and is trivially serialisable to JSON, so both
the Qt frontend and a future web frontend persist position identically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Locator:
    """Where the reader is within a book."""

    spine_index: int
    #: Vertical scroll position within the document, clamped to 0..1.
    progress: float = 0.0
    #: Optional in-document anchor (without '#') to prefer over ``progress``.
    fragment: str = ""

    def __post_init__(self) -> None:
        clamped = 0.0 if self.progress < 0 else 1.0 if self.progress > 1 else self.progress
        object.__setattr__(self, "progress", clamped)

    def to_dict(self) -> dict:
        return {
            "spine_index": self.spine_index,
            "progress": self.progress,
            "fragment": self.fragment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Locator":
        return cls(
            spine_index=int(data.get("spine_index", 0)),
            progress=float(data.get("progress", 0.0)),
            fragment=str(data.get("fragment", "")),
        )


@dataclass(frozen=True)
class Bookmark:
    """A user-saved position within a book: a :class:`Locator` plus a label.

    Kept in the engine layer (not a frontend) so every UI persists and restores
    bookmarks identically through the progress store. ``id`` is a short stable
    handle a frontend can use as a list key without holding the object itself.
    """

    id: str
    locator: Locator
    label: str = ""
    #: ISO-8601 UTC creation time, for stable ordering and display.
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "locator": self.locator.to_dict(),
            "label": self.label,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Bookmark":
        return cls(
            id=str(data.get("id", "")),
            locator=Locator.from_dict(data.get("locator", {})),
            label=str(data.get("label", "")),
            created_at=str(data.get("created_at", "")),
        )
