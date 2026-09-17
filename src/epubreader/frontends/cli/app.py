# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Terminal reader entry point.

Builds a :class:`ReaderSession` on the same JSON store the desktop and web
frontends use — so reading position and bookmarks are shared across all three —
opens the given book, and runs an interactive command loop.

    python -m epubreader.frontends.cli.app path/to/book.epub [--width N] [--no-color]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from ...core.exceptions import EpubError
from ...session.session import ReaderSession
from ...session.storage import JsonProgressStore
from .reader import CliReader

APP_NAME = "epubreader"


def _config_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "state.json"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="epubreader-cli")
    parser.add_argument("book", help="path to an .epub to open")
    parser.add_argument("--width", type=int, default=None, help="wrap width (default: terminal)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI styling")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    session = ReaderSession(JsonProgressStore(_config_path()))
    try:
        session.open(args.book)
    except EpubError as exc:
        print(f"cannot open {args.book}: {exc}", file=sys.stderr)
        return 1

    color = False if args.no_color else None
    reader = CliReader(session, width=args.width, color=color)
    return reader.run()


if __name__ == "__main__":
    raise SystemExit(main())
