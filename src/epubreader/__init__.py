# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""epubreader — a modular EPUB reading engine with a replaceable UI.

Layers, top to bottom:

* :mod:`epubreader.core`      — the UI-agnostic engine (parsing, resources).
* :mod:`epubreader.session`   — stateful reading session + persistence.
* :mod:`epubreader.render`    — shared theme/document transforms.
* :mod:`epubreader.frontend`  — the abstract frontend contract.
* :mod:`epubreader.frontends` — concrete UIs (Qt, web, CLI).
"""

from __future__ import annotations

__version__ = "0.9.1"
__author__ = "Leon Priest"

from .core import Book, EpubError, Locator
from .session import ReaderSession, ReaderSettings

__all__ = [
    "__version__",
    "Book",
    "EpubError",
    "Locator",
    "ReaderSession",
    "ReaderSettings",
]
