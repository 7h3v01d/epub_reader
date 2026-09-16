# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Exception hierarchy for the EPUB engine.

All engine failures derive from :class:`EpubError` so a frontend can catch a
single base type and surface it, without importing any UI framework.
"""

from __future__ import annotations


class EpubError(Exception):
    """Base class for every recoverable engine error."""


class InvalidEpubError(EpubError):
    """The archive is not a structurally valid EPUB (bad container / OPF)."""


class ResourceNotFoundError(EpubError):
    """A resource was requested that does not exist inside the archive."""

    def __init__(self, key: str) -> None:
        super().__init__(f"resource not found: {key!r}")
        self.key = key


class NavigationError(EpubError):
    """A navigation target (spine index / href) could not be resolved."""
