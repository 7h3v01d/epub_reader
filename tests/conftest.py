# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Shared pytest fixtures and src/ path wiring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.make_fixture_epub import build_epub2, build_epub3  # noqa: E402


@pytest.fixture
def epub3_path(tmp_path) -> Path:
    return build_epub3(tmp_path / "fixture3.epub")


@pytest.fixture
def epub2_path(tmp_path) -> Path:
    return build_epub2(tmp_path / "fixture2.epub")
