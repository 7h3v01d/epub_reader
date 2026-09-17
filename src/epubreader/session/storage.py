# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Persistence for reading position and settings.

A :class:`ProgressStore` is an injectable interface so the session never hard
codes a filesystem path — tests pass an in-memory store, the app passes a JSON
store rooted in the user's config directory. JSON is used over TOML by
convention. Writes are atomic (temp file + replace) to avoid truncated state.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..core.locators import Bookmark, Locator
from .settings import ReaderSettings


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    """Best-effort cross-process exclusive lock (advisory).

    Uses ``fcntl`` on POSIX and ``msvcrt`` on Windows; both release
    automatically if the process dies. Failure to lock (exotic filesystem) is
    non-fatal — the read-modify-write below still narrows the race — so the
    reader never wedges on a locking quirk.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")
    locked = False
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        except ImportError:
            try:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                locked = True
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
        yield
    finally:
        if locked:
            with contextlib.suppress(Exception):
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


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

    @abstractmethod
    def add_bookmark(self, book_id: str, bookmark: Bookmark) -> list[Bookmark]:
        """Atomically append one bookmark; returns the resulting list."""

    @abstractmethod
    def remove_bookmark(self, book_id: str, bookmark_id: str) -> list[Bookmark]:
        """Atomically remove one bookmark by id; returns the resulting list."""


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

    def add_bookmark(self, book_id: str, bookmark: Bookmark) -> list[Bookmark]:
        self._bookmarks.setdefault(book_id, []).append(bookmark)
        return list(self._bookmarks[book_id])

    def remove_bookmark(self, book_id: str, bookmark_id: str) -> list[Bookmark]:
        kept = [b for b in self._bookmarks.get(book_id, []) if b.id != bookmark_id]
        self._bookmarks[book_id] = kept
        return list(kept)


class JsonProgressStore(ProgressStore):
    """A single JSON document holding all locators, settings and bookmarks.

    Reads always come from disk and every write is a locked read-modify-write,
    so a desktop and a web reader sharing the file don't clobber each other's
    updates. The file is treated as untrusted input: a wrong-type or corrupt
    document is quarantined and replaced with clean state rather than crashing.
    """

    _EMPTY = {"locators": {}, "settings": {}, "bookmarks": {}}

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")

    def _fresh(self) -> dict:
        return {"locators": {}, "settings": {}, "bookmarks": {}}

    def _read(self) -> dict:
        if not self._path.is_file():
            return self._fresh()
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self._quarantine()
            return self._fresh()
        if not isinstance(data, dict):
            # Valid JSON of the wrong shape (e.g. a top-level list) would break
            # every dict operation below — treat it as corruption.
            self._quarantine()
            return self._fresh()
        # Coerce each section to a dict; ignore anything malformed.
        clean = self._fresh()
        for key in clean:
            section = data.get(key)
            if isinstance(section, dict):
                clean[key] = section
        return clean

    def _quarantine(self) -> None:
        """Move a damaged state file aside so startup can proceed clean."""
        try:
            backup = self._path.with_name(
                f"{self._path.stem}.corrupt.{int(time.time())}{self._path.suffix}"
            )
            os.replace(self._path, backup)
        except OSError:
            pass

    def _write_data(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @contextlib.contextmanager
    def _mutate(self):
        """Locked read-modify-write: reload the latest file, yield it, save it."""
        with _file_lock(self._lock_path):
            data = self._read()
            yield data
            self._write_data(data)

    def get_locator(self, book_id: str) -> Optional[Locator]:
        raw = self._read()["locators"].get(book_id)
        return Locator.from_dict(raw) if isinstance(raw, dict) else None

    def set_locator(self, book_id: str, locator: Locator) -> None:
        with self._mutate() as data:
            data["locators"][book_id] = locator.to_dict()

    def get_settings(self) -> ReaderSettings:
        return ReaderSettings.from_dict(self._read().get("settings", {}))

    def set_settings(self, settings: ReaderSettings) -> None:
        with self._mutate() as data:
            data["settings"] = settings.clamped().to_dict()

    def get_bookmarks(self, book_id: str) -> list[Bookmark]:
        raw = self._read().get("bookmarks", {}).get(book_id, [])
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict):
                with contextlib.suppress(Exception):
                    out.append(Bookmark.from_dict(item))
        return out

    def set_bookmarks(self, book_id: str, bookmarks: list[Bookmark]) -> None:
        with self._mutate() as data:
            data.setdefault("bookmarks", {})[book_id] = [bm.to_dict() for bm in bookmarks]

    def add_bookmark(self, book_id: str, bookmark: Bookmark) -> list[Bookmark]:
        # Locked read-modify-write appends against the *latest* on-disk list, so
        # a second reader adding a bookmark can't overwrite the first's with a
        # stale snapshot (the semantic lost-update the file lock alone missed).
        with self._mutate() as data:
            bookmarks = data.setdefault("bookmarks", {})
            existing = bookmarks.get(book_id)
            if not isinstance(existing, list):   # untrusted state: coerce first
                existing = []
            existing.append(bookmark.to_dict())
            bookmarks[book_id] = existing
        return self.get_bookmarks(book_id)

    def remove_bookmark(self, book_id: str, bookmark_id: str) -> list[Bookmark]:
        with self._mutate() as data:
            bookmarks = data.setdefault("bookmarks", {})
            current = bookmarks.get(book_id)
            if not isinstance(current, list):
                current = []
            bookmarks[book_id] = [
                x for x in current
                if not (isinstance(x, dict) and x.get("id") == bookmark_id)
            ]
        return self.get_bookmarks(book_id)
