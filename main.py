# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Thin launcher for the PyQt6 EPUB reader.

Kept deliberately tiny: it only delegates to the Qt frontend's ``main()``. All
wiring — registering the custom URL scheme *before* the QApplication is built,
locating the config file, constructing the session and window — lives in
``epubreader.frontends.qt.app`` so that this file has nothing worth maintaining.

Run it with the repository's ``src/`` directory on the path. ``run.bat`` does
that for you on Windows; from a shell it is::

    set PYTHONPATH=src        (Windows)
    export PYTHONPATH=src     (POSIX)
    python main.py [optional/path/to/book.epub]
"""

from __future__ import annotations

from epubreader.frontends.qt.app import main

if __name__ == "__main__":
    # main() reads sys.argv itself (argv[0]=program, argv[1]=optional book path).
    raise SystemExit(main())
