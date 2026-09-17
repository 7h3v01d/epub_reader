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
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit binding to a non-loopback interface (LAN exposure)",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    loopback = args.host.lower() in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not args.allow_remote:
        parser.error(
            f"refusing to bind to non-loopback host {args.host!r} without "
            "--allow-remote. The reader has no user accounts; a remote bind is "
            "protected only by a per-launch token that is embedded in the served "
            "page, so anyone who can reach it can read that token."
        )

    frontend = build_frontend(args.book)
    if not loopback:
        print(
            f"WARNING: binding to {args.host} exposes the reader on the network. "
            "Its token is embedded in the page, so treat this as convenience, not "
            "authentication."
        )
    print(f"epubreader web — http://{args.host}:{args.port}")
    return frontend.run(host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
