# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""UI-agnostic EPUB engine.

Importing from :mod:`epubreader.core` never pulls in a UI toolkit, so the
engine can be unit tested and reused behind any frontend.
"""

from __future__ import annotations

from .book import Book
from .exceptions import (
    EpubError,
    InvalidEpubError,
    NavigationError,
    ResourceNotFoundError,
)
from .locators import Bookmark, Locator
from .models import (
    ManifestItem,
    Metadata,
    NavPoint,
    Resource,
    SpineItem,
)
from .search import SearchHit, search_book

__all__ = [
    "Book",
    "EpubError",
    "InvalidEpubError",
    "NavigationError",
    "ResourceNotFoundError",
    "Bookmark",
    "Locator",
    "ManifestItem",
    "Metadata",
    "NavPoint",
    "Resource",
    "SpineItem",
    "SearchHit",
    "search_book",
]
