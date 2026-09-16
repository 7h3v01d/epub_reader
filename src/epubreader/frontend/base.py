# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""The replaceable-UI contract.

A frontend is anything that can present a :class:`ReaderSession`. Implement the
five presentation methods below and the base class wires itself to the session's
callbacks; the concrete UI (Qt window, web server, CLI) then only worries about
*presentation*, calling session navigation methods in response to user input.

To add a web UI, subclass :class:`ReaderFrontend`, map ``section.key`` to an
HTTP route that serves ``session.book.read_resource(key)`` through
:func:`epubreader.render.inject_stylesheet`, and you are done — the engine and
session are reused verbatim.

Note on design: this is a *plain* base class, not an :class:`abc.ABC`. A Qt
frontend inherits from both this and ``QMainWindow``; Qt's ``sip.wrappertype``
metaclass and ``ABCMeta`` are incompatible and raise ``TypeError`` at class
creation. A plain base (metaclass ``type``) composes cleanly, so the unimplemented
methods raise :class:`NotImplementedError` instead of using ``@abstractmethod``.
"""

from __future__ import annotations

from ..core.models import Metadata, NavPoint
from ..session.session import ReaderSession, RenderedSection


class ReaderFrontend:
    """Base class for every UI. Binds to the session on construction.

    Two callback channels are kept separate on purpose:

    * ``on_book_opened`` fires once per book — refresh metadata and the table of
      contents here.
    * ``on_section`` fires on every page turn *and* on settings changes — render
      only the section, so the TOC tree is never cleared and rebuilt underneath a
      user who has expanded or selected a node.
    """

    def __init__(self, *args, **kwargs) -> None:
        # Cooperative on purpose. A Qt subclass inherits as
        # ``class ReaderWindow(QMainWindow, ReaderFrontend)`` and calls a single
        # ``super().__init__()``; QtWidgets' own __init__ then continues up the
        # MRO into this one. If this required a ``session`` argument it would
        # blow up there (QMainWindow.__init__ passes none), so binding is a
        # separate, explicit step via :meth:`bind_session`.
        super().__init__(*args, **kwargs)
        self.session: ReaderSession | None = None

    def bind_session(self, session: ReaderSession) -> None:
        """Attach the session and subscribe to its callback channels.

        Call this once, from the concrete frontend's constructor, after
        ``super().__init__()`` has run.
        """
        self.session = session
        session.on_book_opened(self._handle_book_opened)
        session.on_section(self._handle_section)
        session.on_error(self.report_error)

    def _handle_book_opened(self) -> None:
        # Book-scoped chrome: rebuilt once, when a new book is adopted.
        self.display_metadata(self.session.metadata())
        self.display_toc(self.session.toc())

    def _handle_section(self, section: RenderedSection) -> None:
        # Section-scoped: fires on every navigation and settings change.
        self.display_section(section)

    # ---- required presentation surface ---------------------------------- #
    def display_section(self, section: RenderedSection) -> None:
        """Render the given section (frontend resolves ``section.key`` itself)."""
        raise NotImplementedError

    def display_toc(self, toc: tuple[NavPoint, ...]) -> None:
        """Present/refresh the table of contents."""
        raise NotImplementedError

    def display_metadata(self, metadata: Metadata) -> None:
        """Present/refresh book metadata (title bar, info panel, …)."""
        raise NotImplementedError

    def report_error(self, message: str) -> None:
        """Surface a recoverable engine error to the user."""
        raise NotImplementedError

    def run(self) -> int:
        """Start the UI event loop; return a process exit code."""
        raise NotImplementedError
