# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Reader settings — serialisable to JSON, with deny-first defaults.

``allow_scripts`` defaults to ``False``: book-supplied JavaScript is refused
unless the reader explicitly opts in, per the deny-first posture. Everything
here is plain data so a web frontend can round-trip the same settings.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


def _finite(value: float, default: float) -> float:
    try:
        return value if math.isfinite(value) else default
    except TypeError:
        return default


@dataclass
class ReaderSettings:
    """User-facing rendering preferences."""

    theme: str = "obsidian"       # obsidian | sepia | light
    font_scale: float = 1.0        # 0.6 .. 2.5
    margin_em: float = 2.0         # page inset, in em
    line_height: float = 1.6
    #: Deny-first: book scripts stay disabled unless the user opts in.
    allow_scripts: bool = False
    #: Inject the reader theme stylesheet into served documents.
    inject_theme: bool = True

    def clamped(self) -> "ReaderSettings":
        theme = self.theme if isinstance(self.theme, str) else "obsidian"
        return ReaderSettings(
            theme=theme if theme in {"obsidian", "sepia", "light"} else "obsidian",
            font_scale=min(2.5, max(0.6, _finite(self.font_scale, 1.0))),
            margin_em=min(8.0, max(0.0, _finite(self.margin_em, 2.0))),
            line_height=min(2.4, max(1.0, _finite(self.line_height, 1.6))),
            allow_scripts=bool(self.allow_scripts),
            inject_theme=bool(self.inject_theme),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReaderSettings":
        if not isinstance(data, dict):
            return cls()
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known).clamped()
