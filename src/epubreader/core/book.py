# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The :class:`Book` — the engine's public surface.

A Book opens an EPUB archive, parses its structure eagerly (cheap: only the
container, OPF and TOC), and then serves resource bytes lazily on demand. It is
the single choke point for reading from the archive, which is what lets a
frontend enforce a deny-first policy: nothing reaches a renderer except through
:meth:`read_resource`, and every key is validated against the manifest/namelist.

The class is UI-agnostic and imports no toolkit. Resource reads are guarded by
a lock because a Qt URL-scheme handler may request subresources from the GUI
thread after the initial open completed on a worker thread.
"""

from __future__ import annotations

import hashlib
import mimetypes
import threading
import zipfile
from pathlib import Path
from typing import Optional

from . import container, navigation
from .exceptions import InvalidEpubError, ResourceNotFoundError
from .models import Metadata, NavPoint, Resource, SpineItem
from .package import Package, parse_package

_CONTAINER_KEY = "META-INF/container.xml"


class Book:
    """An opened EPUB. Construct via :meth:`open`; release via :meth:`close`."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._zip: Optional[zipfile.ZipFile] = None
        self._lock = threading.Lock()
        self._names: set[str] = set()
        self._package: Optional[Package] = None
        self._toc: tuple[NavPoint, ...] = ()
        self._book_id: str = ""

    # ---- lifecycle ------------------------------------------------------- #
    @classmethod
    def open(cls, path: str | Path) -> "Book":
        """Open and parse the archive at ``path``. Raises on invalid EPUBs."""
        book = cls(path)
        book._load()
        return book

    def _load(self) -> None:
        if not self._path.is_file():
            raise InvalidEpubError(f"no such file: {self._path}")
        try:
            self._zip = zipfile.ZipFile(self._path, "r")
        except zipfile.BadZipFile as exc:
            raise InvalidEpubError(f"not a zip archive: {exc}") from exc

        self._names = set(self._zip.namelist())
        if _CONTAINER_KEY not in self._names:
            raise InvalidEpubError("missing META-INF/container.xml")

        opf_key = container.find_opf_key(self._raw(_CONTAINER_KEY))
        if opf_key not in self._names:
            raise InvalidEpubError(f"OPF not found in archive: {opf_key}")
        self._package = parse_package(opf_key, self._raw(opf_key))
        self._toc = self._load_toc(self._package)
        self._book_id = self._compute_book_id(self._package.metadata)

    def _load_toc(self, package: Package) -> tuple[NavPoint, ...]:
        nav = package.nav_item()
        if nav is not None and nav.key in self._names:
            try:
                toc = navigation.parse_nav_document(nav.key, self._raw(nav.key))
                if toc:
                    return toc
            except Exception:  # noqa: BLE001 - malformed nav shouldn't kill open
                pass
        if package.ncx_key and package.ncx_key in self._names:
            try:
                return navigation.parse_ncx(package.ncx_key, self._raw(package.ncx_key))
            except Exception:  # noqa: BLE001
                pass
        return ()

    def _compute_book_id(self, meta: Metadata) -> str:
        """A stable id for progress storage: dc:identifier, else a hash."""
        if meta.identifier:
            return meta.identifier
        digest = hashlib.sha1()
        digest.update(self._path.name.encode("utf-8", "replace"))
        digest.update(str(self._path.stat().st_size).encode("ascii"))
        return f"sha1:{digest.hexdigest()}"

    def close(self) -> None:
        with self._lock:
            if self._zip is not None:
                self._zip.close()
                self._zip = None

    def __enter__(self) -> "Book":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- structure accessors -------------------------------------------- #
    @property
    def path(self) -> Path:
        return self._path

    @property
    def book_id(self) -> str:
        return self._book_id

    @property
    def metadata(self) -> Metadata:
        assert self._package is not None
        return self._package.metadata

    @property
    def spine(self) -> tuple[SpineItem, ...]:
        assert self._package is not None
        return self._package.spine

    @property
    def toc(self) -> tuple[NavPoint, ...]:
        return self._toc

    def spine_index_for_key(self, key: str) -> Optional[int]:
        """Reading-order index whose document is ``key``, or ``None``."""
        for item in self.spine:
            if item.key == key:
                return item.index
        return None

    def has_resource(self, key: str) -> bool:
        return key in self._names

    # ---- resource access (the deny-first choke point) ------------------- #
    def _raw(self, key: str) -> bytes:
        assert self._zip is not None
        with self._lock:
            return self._zip.read(key)

    def read_resource(self, key: str) -> Resource:
        """Return bytes + media type for ``key``.

        Only keys that physically exist in the archive are served; anything
        else raises :class:`ResourceNotFoundError`. This is the guarantee a
        frontend relies on to keep a renderer sandboxed to the book.
        """
        if key not in self._names:
            raise ResourceNotFoundError(key)
        data = self._raw(key)
        return Resource(key=key, data=data, media_type=self._media_type(key))

    def _media_type(self, key: str) -> str:
        assert self._package is not None
        for item in self._package.manifest.values():
            if item.key == key:
                return item.media_type
        guessed, _ = mimetypes.guess_type(key)
        return guessed or "application/octet-stream"
