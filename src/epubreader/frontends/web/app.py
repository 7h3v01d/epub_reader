# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Web frontend entry point.

Builds a :class:`ReaderSession` on the same JSON progress store the Qt frontend
uses — so reading position and bookmarks are shared between the two UIs — wraps
it in a :class:`WebFrontend`, optionally opens a book given on the command line,
and serves.

    python -m epubreader.frontends.web.app [book.epub] [--host H] [--port P]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from ...session.session import ReaderSession
from ...session.storage import JsonProgressStore
from .frontend import WebFrontend

APP_NAME = "epubreader"


def _config_path() -> Path:
    """Per-user JSON state file (Windows: %APPDATA%; else ~/.config)."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "state.json"


def build_frontend(book_path: Optional[str] = None) -> WebFrontend:
    session = ReaderSession(JsonProgressStore(_config_path()))
    frontend = WebFrontend(session)
    if book_path:
        frontend.open_path(book_path)
    return frontend


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epubreader-web")
    parser.add_argument("book", nargs="?", help="optional path to an .epub to open")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    frontend = build_frontend(args.book)
    print(f"epubreader web — http://{args.host}:{args.port}")
    return frontend.run(host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
