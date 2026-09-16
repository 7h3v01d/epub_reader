# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The ``epub://`` scheme: the deny-first bridge into QtWebEngine.

Everything a rendered document loads — the document itself and every image,
stylesheet and font — is fetched through :class:`EpubSchemeHandler`, which only
ever returns bytes that :meth:`Book.read_resource` validated against the
archive. A :class:`DenyFirstInterceptor` sits in front as a second line of
defence, blocking any request whose scheme is not on a tight allow-list, so a
book cannot phone home even if it tries.

:func:`register_scheme` MUST run before the ``QApplication`` is constructed;
Qt rejects custom scheme registration afterwards.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PyQt6.QtWebEngineCore import (
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)

from ...core.book import Book
from ...core.exceptions import ResourceNotFoundError
from ...core.paths import canonical_key
from ...render import inject_stylesheet, reader_stylesheet
from ...session.settings import ReaderSettings

SCHEME_NAME = b"epub"
SCHEME_HOST = "book"

# Schemes Chromium legitimately uses for its own internals plus our own.
# Everything else (http/https/file/ftp/ws/…) is blocked: deny-first.
_ALLOWED_SCHEMES = {"epub", "data", "blob", "about", "qrc", "chrome"}


def register_scheme() -> None:
    """Register the ``epub`` scheme. Call once, before ``QApplication``."""
    if QWebEngineUrlScheme.schemeByName(SCHEME_NAME).name():
        return  # already registered
    scheme = QWebEngineUrlScheme(SCHEME_NAME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setDefaultPort(QWebEngineUrlScheme.SpecialPort.PortUnspecified.value)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def url_for_key(key: str, fragment: str = "") -> QUrl:
    """Build ``epub://book/<key>`` for an archive key (percent-encoded)."""
    encoded = quote(key)
    text = f"epub://{SCHEME_HOST}/{encoded}"
    if fragment:
        text += f"#{quote(fragment)}"
    return QUrl(text)


class DenyFirstInterceptor(QWebEngineUrlRequestInterceptor):
    """Blocks every request whose scheme is not explicitly allowed."""

    def interceptRequest(self, info) -> None:  # noqa: N802 (Qt override)
        scheme = info.requestUrl().scheme().lower()
        if scheme not in _ALLOWED_SCHEMES:
            info.block(True)


class EpubSchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves book resources, injecting the reader theme into documents."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._book: Optional[Book] = None
        self._settings = ReaderSettings()
        # GC-safety: keep buffers alive until their request job is destroyed.
        self._buffer_refs: dict[int, QBuffer] = {}

    def set_book(self, book: Optional[Book]) -> None:
        self._book = book

    def set_settings(self, settings: ReaderSettings) -> None:
        self._settings = settings.clamped()

    def requestStarted(self, job) -> None:  # noqa: N802 (Qt override)
        if self._book is None:
            job.fail(job.Error.RequestFailed)
            return
        url: QUrl = job.requestUrl()
        key = canonical_key(url.path())
        try:
            resource = self._book.read_resource(key)
        except ResourceNotFoundError:
            job.fail(job.Error.UrlNotFound)
            return
        except Exception:  # noqa: BLE001 - never leak an exception into Qt
            job.fail(job.Error.RequestFailed)
            return

        data = resource.data
        media = resource.media_type
        if self._settings.inject_theme:
            data = inject_stylesheet(data, media, reader_stylesheet(self._settings))

        buffer = QBuffer(job)
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)

        # Belt-and-suspenders lifetime tracking alongside Qt parenting.
        job_id = id(job)
        self._buffer_refs[job_id] = buffer
        job.destroyed.connect(lambda *_: self._buffer_refs.pop(job_id, None))

        job.reply(media.encode("ascii", "replace"), buffer)
