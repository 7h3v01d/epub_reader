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

import math
from dataclasses import dataclass


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Locator:
    """Where the reader is within a book."""

    spine_index: int
    #: Vertical scroll position within the document, clamped to 0..1.
    progress: float = 0.0
    #: Optional in-document anchor (without '#') to prefer over ``progress``.
    fragment: str = ""

    def __post_init__(self) -> None:
        p = self.progress
        # NaN/inf slip past ordinary < / > comparisons (both are False), so
        # they must be rejected explicitly or they poison persisted state.
        if not math.isfinite(p) or p < 0:
            p = 0.0
        elif p > 1:
            p = 1.0
        object.__setattr__(self, "progress", p)

    def to_dict(self) -> dict:
        return {
            "spine_index": self.spine_index,
            "progress": self.progress,
            "fragment": self.fragment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Locator":
        # Persistence is untrusted: coerce each field, falling back rather than
        # raising on a hostile or malformed value.
        if not isinstance(data, dict):
            return cls(spine_index=0)
        return cls(
            spine_index=_safe_int(data.get("spine_index"), 0),
            progress=_safe_float(data.get("progress"), 0.0),
            fragment=str(data.get("fragment", "")) if data.get("fragment") is not None else "",
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
