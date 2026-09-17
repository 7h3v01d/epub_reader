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
import struct
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

    # ---- hostile-archive budgets (zip-bomb defence) --------------------- #
    #: Reject archives with more members than this.
    MAX_FILE_COUNT = 5000
    #: Largest a single member may decompress to (bounds one read's memory).
    MAX_ENTRY_UNCOMPRESSED = 100 * 1024 * 1024
    #: Largest total declared uncompressed size across all members.
    MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
    #: Per-member compression-ratio ceiling (only enforced above 1 MiB).
    MAX_COMPRESSION_RATIO = 200
    #: Tighter cap for structural XML (container / OPF / nav / NCX).
    MAX_XML_BYTES = 16 * 1024 * 1024
    #: Largest the archive file itself may be on disk (bounds central-directory
    #: memory before the zip is even parsed).
    MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

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
        # Preflight the raw file *before* constructing ZipFile, which would parse
        # the whole central directory (and build a ZipInfo per member) up front.
        self._preflight_archive()
        try:
            self._zip = zipfile.ZipFile(self._path, "r")
        except zipfile.BadZipFile as exc:
            raise InvalidEpubError(f"not a zip archive: {exc}") from exc

        # From here on the archive is open; if any parsing step fails we must
        # not leak the file handle, so close it on the way out.
        try:
            self._check_budgets(self._zip.infolist())
            self._names = set(self._zip.namelist())
            if _CONTAINER_KEY not in self._names:
                raise InvalidEpubError("missing META-INF/container.xml")

            opf_key = container.find_opf_key(self._raw(_CONTAINER_KEY, self.MAX_XML_BYTES))
            if opf_key not in self._names:
                raise InvalidEpubError(f"OPF not found in archive: {opf_key}")
            self._package = parse_package(opf_key, self._raw(opf_key, self.MAX_XML_BYTES))
            self._toc = self._load_toc(self._package)
            self._book_id = self._compute_book_id(self._package.metadata)
        except Exception:
            self.close()
            raise

    def _preflight_archive(self) -> None:
        """Cheap pre-open checks that bound memory before ZipFile parsing."""
        try:
            size = self._path.stat().st_size
        except OSError as exc:
            raise InvalidEpubError(f"cannot stat archive: {exc}") from exc
        if size > self.MAX_ARCHIVE_BYTES:
            raise InvalidEpubError(f"archive file too large ({size} bytes)")
        count = self._declared_entry_count(size)
        if count is not None and count > self.MAX_FILE_COUNT:
            raise InvalidEpubError(f"archive declares too many entries ({count})")

    def _declared_entry_count(self, size: int) -> Optional[int]:
        """Read the End-Of-Central-Directory record's entry count, if findable.

        Best-effort: reads only the archive tail. Returns ``None`` when the EOCD
        can't be located (ZipFile will then apply the post-parse count check).
        """
        try:
            with open(self._path, "rb") as fh:
                fh.seek(max(0, size - 66_000))  # 64 KiB max comment + EOCD record
                tail = fh.read()
        except OSError:
            return None
        idx = tail.rfind(b"PK\x05\x06")
        if idx < 0 or idx + 22 > len(tail):
            return None
        total = struct.unpack_from("<H", tail, idx + 10)[0]
        if total == 0xFFFF:  # Zip64: real count lives in the Zip64 EOCD record
            z = tail.rfind(b"PK\x06\x06")
            if z >= 0 and z + 40 <= len(tail):
                total = struct.unpack_from("<Q", tail, z + 32)[0]
            else:
                return None
        return total

    def _check_budgets(self, infos: list[zipfile.ZipInfo]) -> None:
        """Reject archives that look like decompression bombs, before reading."""
        if len(infos) > self.MAX_FILE_COUNT:
            raise InvalidEpubError(f"archive has too many entries ({len(infos)})")
        total = 0
        for info in infos:
            size = info.file_size
            total += size
            if size > self.MAX_ENTRY_UNCOMPRESSED:
                raise InvalidEpubError(f"archive member too large: {info.filename}")
            if (
                size > 1024 * 1024
                and info.compress_size > 0
                and size / info.compress_size > self.MAX_COMPRESSION_RATIO
            ):
                raise InvalidEpubError(f"suspicious compression ratio: {info.filename}")
        if total > self.MAX_TOTAL_UNCOMPRESSED:
            raise InvalidEpubError(f"archive too large uncompressed ({total} bytes)")

    def _load_toc(self, package: Package) -> tuple[NavPoint, ...]:
        nav = package.nav_item()
        if nav is not None and nav.key in self._names:
            try:
                toc = navigation.parse_nav_document(nav.key, self._raw(nav.key, self.MAX_XML_BYTES))
                if toc:
                    return toc
            except Exception:  # noqa: BLE001 - malformed nav shouldn't kill open
                pass
        if package.ncx_key and package.ncx_key in self._names:
            try:
                return navigation.parse_ncx(
                    package.ncx_key, self._raw(package.ncx_key, self.MAX_XML_BYTES)
                )
            except Exception:  # noqa: BLE001
                pass
        return ()

    def _compute_book_id(self, meta: Metadata) -> str:
        """A stable id for progress storage.

        A ``dc:identifier`` alone is not trustworthy — two different EPUBs can
        declare the same one (accidentally or maliciously), which would merge
        their progress and bookmarks. So identity always includes a content
        fingerprint derived from the archive's central directory (member names,
        sizes and CRCs) — cheap, since it reads no member data.
        """
        fingerprint = self._archive_fingerprint()
        if meta.identifier:
            return f"{meta.identifier}#{fingerprint}"
        return f"sha256:{fingerprint}"

    def _archive_fingerprint(self) -> str:
        assert self._zip is not None
        digest = hashlib.sha256()
        for info in sorted(self._zip.infolist(), key=lambda i: i.filename):
            digest.update(info.filename.encode("utf-8", "replace"))
            digest.update(f"|{info.file_size}|{info.CRC}|".encode("ascii"))
        return digest.hexdigest()[:16]

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
    def _raw(self, key: str, max_bytes: Optional[int] = None) -> bytes:
        cap = self.MAX_ENTRY_UNCOMPRESSED if max_bytes is None else max_bytes
        with self._lock:
            if self._zip is None:
                raise ResourceNotFoundError(key)
            # Stream up to cap+1 bytes so a member whose header understates its
            # size cannot decompress unbounded into memory (zip-bomb defence).
            with self._zip.open(key) as handle:
                data = handle.read(cap + 1)
        if len(data) > cap:
            raise InvalidEpubError(f"resource exceeds size budget: {key}")
        return data

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
