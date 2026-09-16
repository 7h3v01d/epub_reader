# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Persistence for reading position and settings.

A :class:`ProgressStore` is an injectable interface so the session never hard
codes a filesystem path — tests pass an in-memory store, the app passes a JSON
store rooted in the user's config directory. JSON is used over TOML by
convention. Writes are atomic (temp file + replace) to avoid truncated state.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..core.locators import Bookmark, Locator
from .settings import ReaderSettings


class ProgressStore(ABC):
    """Stores a :class:`Locator` per book id and one global settings blob."""

    @abstractmethod
    def get_locator(self, book_id: str) -> Optional[Locator]: ...

    @abstractmethod
    def set_locator(self, book_id: str, locator: Locator) -> None: ...

    @abstractmethod
    def get_settings(self) -> ReaderSettings: ...

    @abstractmethod
    def set_settings(self, settings: ReaderSettings) -> None: ...

    @abstractmethod
    def get_bookmarks(self, book_id: str) -> list[Bookmark]: ...

    @abstractmethod
    def set_bookmarks(self, book_id: str, bookmarks: list[Bookmark]) -> None: ...


class MemoryProgressStore(ProgressStore):
    """Non-persistent store, primarily for tests."""

    def __init__(self) -> None:
        self._locators: dict[str, Locator] = {}
        self._bookmarks: dict[str, list[Bookmark]] = {}
        self._settings = ReaderSettings()

    def get_locator(self, book_id: str) -> Optional[Locator]:
        return self._locators.get(book_id)

    def set_locator(self, book_id: str, locator: Locator) -> None:
        self._locators[book_id] = locator

    def get_settings(self) -> ReaderSettings:
        return self._settings

    def set_settings(self, settings: ReaderSettings) -> None:
        self._settings = settings.clamped()

    def get_bookmarks(self, book_id: str) -> list[Bookmark]:
        return list(self._bookmarks.get(book_id, []))

    def set_bookmarks(self, book_id: str, bookmarks: list[Bookmark]) -> None:
        self._bookmarks[book_id] = list(bookmarks)


class JsonProgressStore(ProgressStore):
    """A single JSON document holding all locators and settings."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data = self._read()

    def _read(self) -> dict:
        if not self._path.is_file():
            return {"locators": {}, "settings": {}, "bookmarks": {}}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            data.setdefault("locators", {})
            data.setdefault("settings", {})
            data.setdefault("bookmarks", {})
            return data
        except (json.JSONDecodeError, OSError):
            return {"locators": {}, "settings": {}, "bookmarks": {}}

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def get_locator(self, book_id: str) -> Optional[Locator]:
        raw = self._data["locators"].get(book_id)
        return Locator.from_dict(raw) if raw else None

    def set_locator(self, book_id: str, locator: Locator) -> None:
        self._data["locators"][book_id] = locator.to_dict()
        self._write()

    def get_settings(self) -> ReaderSettings:
        return ReaderSettings.from_dict(self._data.get("settings", {}))

    def set_settings(self, settings: ReaderSettings) -> None:
        self._data["settings"] = settings.clamped().to_dict()
        self._write()

    def get_bookmarks(self, book_id: str) -> list[Bookmark]:
        raw = self._data.get("bookmarks", {}).get(book_id, [])
        return [Bookmark.from_dict(item) for item in raw]

    def set_bookmarks(self, book_id: str, bookmarks: list[Bookmark]) -> None:
        self._data.setdefault("bookmarks", {})[book_id] = [
            bm.to_dict() for bm in bookmarks
        ]
        self._write()
