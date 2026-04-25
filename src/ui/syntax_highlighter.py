"""FlowArchitect — Syntax Highlighters for YAML and JSON editors.

Supports:
  - YAML: keys, quoted strings, numbers, booleans, comments, list dashes
  - JSON: keys, string values, numbers, booleans/null
  - Both: {{PARAM_NAME}} placeholders
      • Unfilled → accent orange   (user still needs to fill this)
      • Filled   → accent green    (value is set in PlaceholderPanel)

Usage:
    from src.ui.syntax_highlighter import attach_yaml_highlighter, attach_json_highlighter
    from src.ui.theme_manager import ThemeManager

    self._yaml_hl = attach_yaml_highlighter(
        self.yaml_edit.document(),
        ThemeManager.get().current,
    )
    self._json_hl = attach_json_highlighter(
        self.json_edit.document(),
        ThemeManager.get().current,
    )

When theme changes or the set of filled placeholder names changes, call
attach_* again (old highlighter is detached automatically when the new
one takes over), or call update_filled() on the existing instance.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)


# ── Theme color sets ──────────────────────────────────────────────────────────

_YAML_COLORS_DARK: dict[str, str] = {
    "key":                "#7DD3FC",   # sky-300
    "string":             "#86EFAC",   # green-300
    "number":             "#FCA5A5",   # red-300
    "comment":            "#64748B",   # slate-500
    "boolean":            "#F472B6",   # pink-400
    "anchor":             "#94A3B8",   # slate-400
    "placeholder":        "#FB923C",   # orange-400  {{PARAM}} — unfilled
    "placeholder_filled": "#4ADE80",   # green-400   {{PARAM}} — filled ✓
}

_YAML_COLORS_LIGHT: dict[str, str] = {
    "key":                "#1D4ED8",   # blue-700
    "string":             "#15803D",   # green-700
    "number":             "#B91C1C",   # red-700
    "comment":            "#94A3B8",   # slate-400
    "boolean":            "#7C3AED",   # violet-700
    "anchor":             "#6B7280",   # gray-500
    "placeholder":        "#C2410C",   # orange-700
    "placeholder_filled": "#16A34A",   # green-700
}

_JSON_COLORS_DARK: dict[str, str] = {
    "key":                "#7DD3FC",   # sky-300
    "string":             "#86EFAC",   # green-300
    "number":             "#FCA5A5",   # red-300
    "boolean":            "#F472B6",   # pink-400
    "brace":              "#94A3B8",   # slate-400
    "placeholder":        "#FB923C",   # orange-400
    "placeholder_filled": "#4ADE80",   # green-400
}

_JSON_COLORS_LIGHT: dict[str, str] = {
    "key":                "#1D4ED8",
    "string":             "#15803D",
    "number":             "#B91C1C",
    "boolean":            "#7C3AED",
    "brace":              "#6B7280",
    "placeholder":        "#C2410C",
    "placeholder_filled": "#16A34A",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


def _build_filled_pattern(names: frozenset[str]) -> QRegularExpression | None:
    """Build a regex that matches any *filled* placeholder by name."""
    if not names:
        return None
    escaped = "|".join(re.escape(n) for n in sorted(names))
    return QRegularExpression(rf"\{{\{{({escaped})\}}\}}")


# ── YAML Highlighter ──────────────────────────────────────────────────────────

class YamlHighlighter(QSyntaxHighlighter):
    """Regex-based YAML syntax highlighter with placeholder fill-state support."""

    def __init__(
        self,
        document: QTextDocument,
        colors: dict[str, str],
        filled_names: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(document)
        self._colors = colors
        self._filled_names = filled_names
        self._build_rules()

    def _build_rules(self) -> None:
        c = self._colors
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = [
            # YAML keys: word(s) before a colon at start of line (allow dashes/dots)
            (QRegularExpression(r"^\s*[\w.\-]+(?=\s*:)"), _fmt(c["key"])),
            # Double-quoted strings
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt(c["string"])),
            # Single-quoted strings
            (QRegularExpression(r"'[^']*'"), _fmt(c["string"])),
            # Numbers (integer and float)
            (QRegularExpression(r"\b\d+(\.\d+)?\b"), _fmt(c["number"])),
            # Boolean / null
            (QRegularExpression(r"\b(true|false|null|yes|no|on|off)\b"), _fmt(c["boolean"])),
            # Comments
            (QRegularExpression(r"#[^\n]*"), _fmt(c["comment"], italic=True)),
            # List item dash
            (QRegularExpression(r"^\s*-\s"), _fmt(c["anchor"])),
            # All {{PARAM}} placeholders — unfilled (orange); listed last so
            # the filled rule below can override specific ones
            (QRegularExpression(r"\{\{[^}]+\}\}"), _fmt(c["placeholder"], bold=True)),
        ]
        # Filled placeholders (green) — applied after all other rules
        self._filled_pattern = _build_filled_pattern(self._filled_names)
        self._filled_fmt = _fmt(c["placeholder_filled"], bold=True)

    def update_filled(self, names: set[str]) -> None:
        """Update the set of filled placeholder names and rehighlight."""
        self._filled_names = frozenset(names)
        self._build_rules()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Override orange with green for filled placeholders
        if self._filled_pattern is not None:
            it = self._filled_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), self._filled_fmt)


# ── JSON Highlighter ──────────────────────────────────────────────────────────

class JsonHighlighter(QSyntaxHighlighter):
    """Regex-based JSON syntax highlighter with placeholder fill-state support."""

    def __init__(
        self,
        document: QTextDocument,
        colors: dict[str, str],
        filled_names: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(document)
        self._colors = colors
        self._filled_names = filled_names
        self._build_rules()

    def _build_rules(self) -> None:
        c = self._colors
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = [
            # Object keys: quoted string before a colon
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"\s*(?=:)'), _fmt(c["key"])),
            # String values: quoted string after colon or in array
            (QRegularExpression(r'(?<=:\s)"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt(c["string"])),
            (QRegularExpression(r'(?<=,\s)"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt(c["string"])),
            (QRegularExpression(r'(?<=\[)"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt(c["string"])),
            # Simpler string catch-all (runs after key rule)
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), _fmt(c["string"])),
            # Numbers
            (QRegularExpression(r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b"), _fmt(c["number"])),
            # Booleans and null
            (QRegularExpression(r"\b(true|false|null)\b"), _fmt(c["boolean"])),
            # Structural chars (subtle)
            (QRegularExpression(r"[{}\[\]]"), _fmt(c["brace"])),
            # All {{PARAM}} placeholders — unfilled (orange)
            (QRegularExpression(r"\{\{[^}]+\}\}"), _fmt(c["placeholder"], bold=True)),
        ]
        self._filled_pattern = _build_filled_pattern(self._filled_names)
        self._filled_fmt = _fmt(c["placeholder_filled"], bold=True)

    def update_filled(self, names: set[str]) -> None:
        """Update the set of filled placeholder names and rehighlight."""
        self._filled_names = frozenset(names)
        self._build_rules()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        if self._filled_pattern is not None:
            it = self._filled_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), self._filled_fmt)


# ── Factory functions ─────────────────────────────────────────────────────────

def attach_yaml_highlighter(
    document: QTextDocument,
    theme: str = "dark",
    filled_names: frozenset[str] = frozenset(),
) -> YamlHighlighter:
    """Create and attach a YamlHighlighter to *document*."""
    colors = _YAML_COLORS_DARK if theme == "dark" else _YAML_COLORS_LIGHT
    return YamlHighlighter(document, colors, filled_names)


def attach_json_highlighter(
    document: QTextDocument,
    theme: str = "dark",
    filled_names: frozenset[str] = frozenset(),
) -> JsonHighlighter:
    """Create and attach a JsonHighlighter to *document*."""
    colors = _JSON_COLORS_DARK if theme == "dark" else _JSON_COLORS_LIGHT
    return JsonHighlighter(document, colors, filled_names)
