# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""PyQt6 + QtWebEngine frontend."""

from __future__ import annotations

__all__ = ["main", "ReaderWindow"]


def __getattr__(name):
    # Lazy imports so importing the package never forces PyQt6 to load.
    if name == "main":
        from .app import main
        return main
    if name == "ReaderWindow":
        from .window import ReaderWindow
        return ReaderWindow
    raise AttributeError(name)
