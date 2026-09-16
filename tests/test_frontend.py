# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Frontend-contract tests that need no GUI toolkit.

These guard the multiple-inheritance construction path that the Qt window uses
without importing PyQt6. ``_FakeQt`` stands in for ``QMainWindow``: the one
behaviour that matters here is that its ``__init__`` cooperatively calls
``super().__init__()``, which is exactly what makes a naive ``ReaderFrontend``
mixin blow up. If :class:`ReaderFrontend` ever regresses to requiring a
``session`` argument in ``__init__``, constructing ``_FakeWindow`` raises
``TypeError`` and these tests fail — the same failure seen with the real
``QMainWindow``.
"""

from __future__ import annotations

from epubreader.frontend.base import ReaderFrontend
from epubreader.session.session import ReaderSession
from epubreader.session.storage import MemoryProgressStore


class _FakeQt:
    """Mimics QMainWindow: its __init__ calls super().__init__() cooperatively."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.qt_inited = True


class _FakeWindow(_FakeQt, ReaderFrontend):
    """A frontend built like ReaderWindow: one super().__init__(), then bind."""

    def __init__(self, session: ReaderSession) -> None:
        super().__init__()
        self.calls = {"meta": 0, "toc": 0, "section": 0, "error": 0}
        self.bind_session(session)

    def display_section(self, section) -> None:  # noqa: ANN001
        self.calls["section"] += 1

    def display_toc(self, toc) -> None:  # noqa: ANN001
        self.calls["toc"] += 1

    def display_metadata(self, metadata) -> None:  # noqa: ANN001
        self.calls["meta"] += 1

    def report_error(self, message) -> None:  # noqa: ANN001
        self.calls["error"] += 1

    def run(self) -> int:
        return 0


def test_frontend_constructs_under_cooperative_super():
    # The regression: this construction raised
    # "ReaderFrontend.__init__() missing 1 required positional argument".
    session = ReaderSession(MemoryProgressStore())
    window = _FakeWindow(session)
    assert window.qt_inited is True
    assert window.session is session


def test_bind_session_wires_book_and_section_channels(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    window = _FakeWindow(session)
    session.open(epub3_path)
    # Book-opened rebuilds metadata + TOC once; the first section renders once.
    assert window.calls["meta"] == 1
    assert window.calls["toc"] == 1
    assert window.calls["section"] == 1


def test_navigation_renders_section_without_rebuilding_chrome(epub3_path):
    session = ReaderSession(MemoryProgressStore())
    window = _FakeWindow(session)
    session.open(epub3_path)
    session.next_section()
    assert window.calls["section"] == 2   # re-rendered
    assert window.calls["meta"] == 1       # chrome untouched
    assert window.calls["toc"] == 1


def test_error_channel_reaches_frontend():
    session = ReaderSession(MemoryProgressStore())
    window = _FakeWindow(session)
    session._emit_error("boom")            # engine surfaces a recoverable error
    assert window.calls["error"] == 1
