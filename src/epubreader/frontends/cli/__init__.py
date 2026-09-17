# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Terminal frontend (pure standard library)."""

from __future__ import annotations

__all__ = ["main", "CliReader"]


def __getattr__(name):
    if name == "main":
        from .app import main
        return main
    if name == "CliReader":
        from .reader import CliReader
        return CliReader
    raise AttributeError(name)
