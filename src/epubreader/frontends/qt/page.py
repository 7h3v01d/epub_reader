# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""A locked-down :class:`QWebEnginePage` for rendering book content.

Navigation is deny-first: only ``epub://`` targets load in place. Any external
link is refused and re-emitted as :pyattr:`external_link_requested` so the
window can decide (default: ignore). JavaScript, plugins, remote/file access
and screen capture are all disabled unless settings explicitly relax them.
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from ...session.settings import ReaderSettings


class ReaderPage(QWebEnginePage):
    """Sandboxed page bound to the ``epub`` scheme."""

    external_link_requested = pyqtSignal(QUrl)

    def __init__(self, profile, parent=None) -> None:
        super().__init__(profile, parent)
        self.apply_settings(ReaderSettings())

    def apply_settings(self, settings: ReaderSettings) -> None:
        s = self.settings()
        A = QWebEngineSettings.WebAttribute
        s.setAttribute(A.JavascriptEnabled, settings.allow_scripts)
        s.setAttribute(A.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(A.LocalContentCanAccessFileUrls, False)
        s.setAttribute(A.ErrorPageEnabled, False)
        s.setAttribute(A.PluginsEnabled, False)
        s.setAttribute(A.ScreenCaptureEnabled, False)
        s.setAttribute(A.FullScreenSupportEnabled, False)
        s.setAttribute(A.AllowRunningInsecureContent, False)
        s.setAttribute(A.JavascriptCanOpenWindows, False)
        s.setAttribute(A.JavascriptCanAccessClipboard, False)

    def acceptNavigationRequest(  # noqa: N802 (Qt override)
        self, url: QUrl, nav_type, is_main_frame: bool
    ) -> bool:
        if url.scheme() == "epub":
            return True
        # Anything else (http/https/mailto/file/…) is refused here.
        if is_main_frame and url.scheme() in {"http", "https"}:
            self.external_link_requested.emit(url)
        return False
