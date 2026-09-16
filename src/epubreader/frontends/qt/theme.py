# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Leon Priest <github.com/7h3v01d>
"""Qt chrome styling — the house design system rendered as a QSS string.

Obsidian / Panel / Border / Teal / Phosphor / Amber / Red / Text, JetBrains
Mono, flat zero-radius controls. This styles the *window chrome* only; the
reading surface itself is themed by :func:`epubreader.render.reader_stylesheet`.
"""

from __future__ import annotations

OBSIDIAN = "#0b0f14"
PANEL = "#11161d"
BORDER = "#1e2831"
TEAL = "#2fd6c3"
PHOSPHOR = "#4be08a"
AMBER = "#ffb454"
RED = "#ff6b6b"
TEXT = "#c8d3da"

FONT_FAMILY = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'

QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background: {OBSIDIAN};
}}
QToolBar {{
    background: {PANEL};
    border: 0px;
    border-bottom: 1px solid {BORDER};
    spacing: 2px;
    padding: 4px;
}}
QToolButton, QPushButton {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 6px 12px;
}}
QToolButton:hover, QPushButton:hover {{
    border-color: {TEAL};
    color: {TEAL};
}}
QToolButton:disabled, QPushButton:disabled {{
    color: {BORDER};
    border-color: {BORDER};
}}
QToolButton:pressed, QPushButton:pressed {{
    background: {BORDER};
}}
QDockWidget {{
    titlebar-close-icon: none;
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QDockWidget::title {{
    background: {PANEL};
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER};
}}
QTreeWidget, QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    outline: 0;
}}
QTreeWidget::item, QListWidget::item {{
    padding: 4px 6px;
    border: 0px;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {BORDER};
    color: {TEAL};
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    color: {PHOSPHOR};
}}
QLabel#StatusLabel {{
    color: {AMBER};
    padding: 4px 8px;
}}
QLabel#ErrorLabel {{
    color: {RED};
    padding: 4px 8px;
}}
QStatusBar {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
}}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 4px 6px;
}}
QComboBox:hover {{ border-color: {TEAL}; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {BORDER};
    selection-color: {TEAL};
}}
QCheckBox {{ spacing: 6px; }}
QScrollBar:vertical {{
    background: {OBSIDIAN};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 24px;
    border-radius: 0px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEAL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
