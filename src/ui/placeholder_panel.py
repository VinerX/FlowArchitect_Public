"""FlowArchitect — PlaceholderPanel

Collapsible panel rendered below the PIM/PSM editor tabs.
Displays a table of all {{PLACEHOLDER}} names found in both editors,
lets the user fill them in, mark them as global (persisted) or sensitive
(masked in the UI).

Signals:
    filled_changed(names: set)  — emitted whenever any value is changed;
                                  carries the current set of filled names
                                  so the caller can update syntax highlighting.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.managers.placeholder_manager import PlaceholderManager
from src.ui.theme_manager import ThemeManager


class PlaceholderPanel(QWidget):
    """Collapsible placeholder management panel."""

    # Emitted whenever a value is set/cleared; payload = set of filled names
    filled_changed = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("placeholder_panel")

        self._store = PlaceholderManager()
        self._collapsed = True
        self._current_names: set[str] = set()

        # Debounce rebuilds triggered by textChanged
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(400)
        self._rebuild_timer.timeout.connect(self._rebuild_table)

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toggle header ──────────────────────────────────────────────
        header = QFrame(self)
        header.setObjectName("placeholder_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(6)

        self._toggle_btn = QPushButton("▶  Placeholders  (0 / 0 filled)", self)
        self._toggle_btn.setObjectName("placeholder_toggle")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_panel)

        self._hint_label = QLabel(
            "Fill in {{PLACEHOLDER}} values — they will be substituted on export, never sent to LLM",
            self,
        )
        self._hint_label.setObjectName("placeholder_hint")
        font = QFont()
        font.setPointSize(8)
        self._hint_label.setFont(font)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_layout.addWidget(self._toggle_btn)
        header_layout.addWidget(self._hint_label)

        # ── Content area ───────────────────────────────────────────────
        self._content = QFrame(self)
        self._content.setObjectName("placeholder_content")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(8, 4, 8, 8)
        content_layout.setSpacing(4)

        self._table = QTableWidget(0, 4, self)
        self._table.setObjectName("placeholder_table")
        self._table.setHorizontalHeaderLabels(["Name", "Value", "🌐 Global", "🔒 Sensitive"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setAlternatingRowColors(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setMaximumHeight(220)

        content_layout.addWidget(self._table)
        self._content.setVisible(False)

        root.addWidget(header)
        root.addWidget(self._content)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_from_text(self, yaml_text: str, json_text: str) -> None:
        """Scan both editor texts and schedule a table rebuild."""
        names = self._store.scan_text(yaml_text, json_text)
        self._store.ensure_entries(names)
        self._store.remove_stale(names)
        if names != self._current_names:
            self._current_names = names
            self._rebuild_timer.start()
        else:
            # Only the header needs refreshing (fill count may have changed)
            self._update_header()

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _rebuild_table(self) -> None:
        """Fully rebuild the table rows from the current store."""
        # Block signals to avoid cascading updates while populating
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        entries = self._store.all_entries()
        for name in sorted(self._current_names):
            entry = entries.get(name)
            if entry is None:
                continue

            row = self._table.rowCount()
            self._table.insertRow(row)

            # ── Col 0: Name ────────────────────────────────────────────
            name_item = QTableWidgetItem(f"{{{{{name}}}}}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._apply_name_color(name_item, entry.is_filled())
            self._table.setItem(row, 0, name_item)

            # ── Col 1: Value (inline QLineEdit) ────────────────────────
            value_edit = QLineEdit(entry.value)
            value_edit.setObjectName("placeholder_value_edit")
            if entry.should_mask_in_ui():
                value_edit.setEchoMode(QLineEdit.EchoMode.Password)
            value_edit.setPlaceholderText(f"Enter {name}…")
            # Use a factory function to capture `name` by value
            value_edit.textChanged.connect(self._make_value_handler(name, row))
            self._table.setCellWidget(row, 1, value_edit)

            # ── Col 2: Global checkbox ─────────────────────────────────
            self._table.setCellWidget(row, 2, self._make_checkbox(
                entry.is_global,
                self._make_global_handler(name),
            ))

            # ── Col 3: Sensitive checkbox ──────────────────────────────
            self._table.setCellWidget(row, 3, self._make_checkbox(
                entry.is_sensitive or entry.auto_sensitive,
                self._make_sensitive_handler(name, row),
            ))

        self._table.blockSignals(False)
        self._update_header()
        self.filled_changed.emit(self._store.filled_names())

    # ── Handlers ──────────────────────────────────────────────────────

    def _make_value_handler(self, name: str, row: int):
        def _on_value(text: str) -> None:
            self._store.set_value(name, text)
            # Update name cell color immediately
            item = self._table.item(row, 0)
            if item:
                self._apply_name_color(item, bool(text.strip()))
            self._update_header()
            self.filled_changed.emit(self._store.filled_names())
        return _on_value

    def _make_global_handler(self, name: str):
        def _on_global(checked: bool) -> None:
            self._store.set_global(name, checked)
        return _on_global

    def _make_sensitive_handler(self, name: str, row: int):
        def _on_sensitive(checked: bool) -> None:
            self._store.set_sensitive(name, checked)
            # Update echo mode of the value editor
            widget = self._table.cellWidget(row, 1)
            if isinstance(widget, QLineEdit):
                mode = (QLineEdit.EchoMode.Password if checked
                        else QLineEdit.EchoMode.Normal)
                widget.setEchoMode(mode)
        return _on_sensitive

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _make_checkbox(checked: bool, handler) -> QWidget:
        """Return a centered-checkbox wrapper widget."""
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.toggled.connect(handler)
        layout.addWidget(cb)
        return wrapper

    def _apply_name_color(self, item: QTableWidgetItem, is_filled: bool) -> None:
        theme = ThemeManager.get().current
        if is_filled:
            color = "#4ADE80" if theme == "dark" else "#16A34A"
        else:
            color = "#FB923C" if theme == "dark" else "#C2410C"
        item.setForeground(QColor(color))
        font = QFont()
        font.setBold(True)
        item.setFont(font)

    def _update_header(self) -> None:
        entries = self._store.all_entries()
        # Only count entries currently visible (in _current_names)
        visible = {n: e for n, e in entries.items() if n in self._current_names}
        total = len(visible)
        filled = sum(1 for e in visible.values() if e.is_filled())
        arrow = "▼" if not self._collapsed else "▶"
        self._toggle_btn.setText(
            f"{arrow}  Placeholders  ({total} / {filled} filled)"
        )
        # Tint the toggle button if there are unfilled placeholders
        theme = ThemeManager.get().current
        if total > 0 and filled < total:
            color = "#FB923C" if theme == "dark" else "#C2410C"
        elif total > 0:
            color = "#4ADE80" if theme == "dark" else "#16A34A"
        else:
            color = ""
        style = f"color: {color}; font-weight: bold;" if color else ""
        self._toggle_btn.setStyleSheet(style)

    def _toggle_panel(self) -> None:
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._update_header()
