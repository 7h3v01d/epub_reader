# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""FastAPI + vanilla-JS web frontend."""

from __future__ import annotations

__all__ = ["main", "WebFrontend", "create_app"]


def __getattr__(name):
    # Lazy imports so importing the package never forces FastAPI to load.
    if name == "main":
        from .app import main
        return main
    if name == "WebFrontend":
        from .frontend import WebFrontend
        return WebFrontend
    if name == "create_app":
        from .server import create_app
        return create_app
    raise AttributeError(name)
