# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Qt frontend entry point.

Ordering matters: the ``epub`` scheme must be registered *before* the
``QApplication`` is created, so :func:`register_scheme` runs first of all. The
session is built on a JSON progress store rooted in the platform config dir.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .scheme import register_scheme

# Register the custom scheme at import time, ahead of any QApplication.
register_scheme()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from ...session.session import ReaderSession  # noqa: E402
from ...session.storage import JsonProgressStore  # noqa: E402
from .window import ReaderWindow  # noqa: E402

APP_NAME = "epubreader"


def _config_path() -> Path:
    """Per-user JSON state file (Windows: %APPDATA%; else ~/.config)."""
    import os

    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "state.json"


def build_window(book_path: Optional[str] = None) -> ReaderWindow:
    store = JsonProgressStore(_config_path())
    session = ReaderSession(store)
    window = ReaderWindow(session)
    if book_path:
        window.open_path(book_path)
    return window


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Leon Priest")

    book_path = argv[1] if len(argv) > 1 else None
    window = build_window(book_path)
    return window.run()


if __name__ == "__main__":
    raise SystemExit(main())
