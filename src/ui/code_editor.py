from __future__ import annotations

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.managers.placeholder_manager import PlaceholderManager
from src.ui.placeholder_panel import PlaceholderPanel
from src.ui.syntax_highlighter import attach_json_highlighter, attach_yaml_highlighter
from src.ui.theme_manager import ThemeManager

_PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")


class CodeEditor(QWidget):
    EXPANDED_MIN_WIDTH = 280
    COLLAPSED_WIDTH = 28

    generate_requested = pyqtSignal(str, int)
    save_yaml_requested = pyqtSignal()
    save_json_requested = pyqtSignal()
    import_nifi_requested = pyqtSignal(str)
    run_ui_task_signal = pyqtSignal(object)
    collapse_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("editor_panel")
        self.setProperty("collapsed", False)
        self._collapsed = False
        self._store = PlaceholderManager()
        self._yaml_hl = None
        self._json_hl = None

        self.run_ui_task_signal.connect(self._run_ui_task)
        self.setMinimumWidth(self.EXPANDED_MIN_WIDTH)

        self.tabs = QTabWidget(self)
        self.yaml_edit = QPlainTextEdit(self)
        self.yaml_edit.setObjectName("code_view")
        self.yaml_edit.setPlaceholderText(
            "PIM (YAML) will appear here after generating from chat..."
        )

        self.json_edit = QPlainTextEdit(self)
        self.json_edit.setObjectName("code_view")
        self.json_edit.setPlaceholderText(
            "PSM (NiFi JSON) will appear here after conversion..."
        )

        self.tabs.addTab(self.yaml_edit, "PIM — YAML")
        self.tabs.addTab(self.json_edit, "PSM — NiFi JSON")

        self._attach_highlighters(ThemeManager.get().current)
        ThemeManager.get().register_on_change(self._on_theme_changed)

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(["Direct", "Adapter", "LLM x2", "Adapter + Fix"])
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setToolTip(
            "Conversion mode:\n"
            "Direct = NL -> JSON\n"
            "Adapter = NL -> PIM -> adapter JSON\n"
            "LLM x2 = NL -> PIM -> LLM JSON\n"
            "Adapter + Fix = adapter JSON + LLM corrector"
        )
        self.mode_combo.setMinimumContentsLength(14)
        self.mode_combo.setMinimumWidth(140)
        self.mode_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.mode_combo.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self.adapter_btn = QPushButton("Adapter JSON", self)
        self.adapter_btn.setObjectName("btn_primary")
        self.adapter_btn.setToolTip(
            "Convert PIM YAML to NiFi JSON with the deterministic adapter"
        )
        self.adapter_btn.setEnabled(False)

        self.llm_json_btn = QPushButton("LLM JSON", self)
        self.llm_json_btn.setToolTip(
            "Convert PIM YAML to NiFi JSON with the configured LLM provider"
        )
        self.llm_json_btn.setEnabled(False)

        self.adapter_llm_btn = QPushButton("Adapter + Fix", self)
        self.adapter_llm_btn.setToolTip(
            "Run adapter conversion, then ask the NiFi JSON corrector to fix semantic errors"
        )
        self.adapter_llm_btn.setEnabled(False)

        self.save_yaml_btn = QPushButton("Save PIM", self)
        self.save_yaml_btn.setToolTip("Save PIM (YAML) to file")
        self.save_yaml_btn.setEnabled(False)

        self.save_json_btn = QPushButton("Save JSON", self)
        self.save_json_btn.setToolTip("Save PSM (NiFi JSON) to file")
        self.save_json_btn.setEnabled(False)

        self.import_nifi_btn = QPushButton("Import NiFi", self)
        self.import_nifi_btn.setObjectName("btn_nifi")
        self.import_nifi_btn.setToolTip("Import current PSM JSON into NiFi")
        self.import_nifi_btn.setEnabled(False)

        self._placeholder_label = QLabel("", self)
        self._placeholder_label.setObjectName("placeholder_counter")
        self._placeholder_label.setToolTip(
            "Number of {{PLACEHOLDER}} values that must be filled before deployment"
        )
        self._placeholder_label.setVisible(False)

        self._next_placeholder_btn = QPushButton("↓ Next", self)
        self._next_placeholder_btn.setObjectName("btn_next_placeholder")
        self._next_placeholder_btn.setToolTip("Jump to next placeholder")
        self._next_placeholder_btn.setVisible(False)
        self._next_placeholder_btn.clicked.connect(self._goto_next_placeholder)

        for btn in (
            self.adapter_btn,
            self.llm_json_btn,
            self.adapter_llm_btn,
            self.save_yaml_btn,
            self.save_json_btn,
            self.import_nifi_btn,
            self._next_placeholder_btn,
        ):
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.adapter_btn.clicked.connect(lambda: self._emit_generate(1))
        self.llm_json_btn.clicked.connect(lambda: self._emit_generate(2))
        self.adapter_llm_btn.clicked.connect(lambda: self._emit_generate(3))
        self.save_yaml_btn.clicked.connect(self.save_yaml_requested)
        self.save_json_btn.clicked.connect(self.save_json_requested)
        self.import_nifi_btn.clicked.connect(self._on_import_nifi_clicked)

        self.yaml_edit.textChanged.connect(self._on_text_changed)
        self.json_edit.textChanged.connect(self._on_text_changed)
        self.mode_combo.currentIndexChanged.connect(self._update_button_states)
        self.tabs.currentChanged.connect(self._update_button_states)

        self.placeholder_panel = PlaceholderPanel(self)
        self.placeholder_panel.filled_changed.connect(self._on_filled_changed)

        self._btn_toggle = QToolButton(self)
        self._btn_toggle.setObjectName("panel_toggle")
        self._btn_toggle.setText("\u00bb")
        self._btn_toggle.setToolTip("Collapse editor panel")
        self._btn_toggle.setFixedSize(24, 24)
        self._btn_toggle.clicked.connect(self.toggle_collapse)

        toolbar = QFrame()
        toolbar.setObjectName("editor_toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 6, 10, 6)
        toolbar_layout.setSpacing(8)

        self._toolbar_details = QWidget(toolbar)
        self._toolbar_details.setObjectName("editor_toolbar_body")
        details_layout = QVBoxLayout(self._toolbar_details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        top_row.addWidget(self.mode_combo)
        top_row.addWidget(self.adapter_btn)
        top_row.addWidget(self.llm_json_btn)
        top_row.addWidget(self.adapter_llm_btn)
        top_row.addStretch(1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)
        bottom_row.addWidget(self._placeholder_label)
        bottom_row.addWidget(self._next_placeholder_btn)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.save_yaml_btn)
        bottom_row.addWidget(self.save_json_btn)
        bottom_row.addWidget(self.import_nifi_btn)

        details_layout.addLayout(top_row)
        details_layout.addLayout(bottom_row)

        toolbar_layout.addWidget(self._toolbar_details, 1)
        toolbar_layout.addWidget(self._btn_toggle, 0)
        self._toolbar = toolbar

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.placeholder_panel)
        self.setLayout(layout)
        self._toolbar.setFixedHeight(self._toolbar.sizeHint().height())

        self._update_button_states()

    def _attach_highlighters(self, theme: str) -> None:
        filled = self._store.filled_names() if hasattr(self, "_store") else frozenset()
        if self._yaml_hl is not None:
            self._yaml_hl.setDocument(None)
        if self._json_hl is not None:
            self._json_hl.setDocument(None)
        self._yaml_hl = attach_yaml_highlighter(
            self.yaml_edit.document(), theme, frozenset(filled)
        )
        self._json_hl = attach_json_highlighter(
            self.json_edit.document(), theme, frozenset(filled)
        )

    def _on_theme_changed(self, theme_name: str) -> None:
        self._attach_highlighters(theme_name)
        self._update_placeholder_counter()

    def _run_ui_task(self, fn):
        if callable(fn):
            fn()

    def toggle_collapse(self) -> None:
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def _collapse(self) -> None:
        self._collapsed = True
        self.setProperty("collapsed", True)
        self._toolbar_details.hide()
        self.tabs.hide()
        self.placeholder_panel.hide()
        self._btn_toggle.setText("\u00ab")
        self._btn_toggle.setToolTip("Expand editor panel")
        self._toolbar.setFixedHeight(44)
        self.setMinimumWidth(self.COLLAPSED_WIDTH)
        self.setMaximumWidth(self.COLLAPSED_WIDTH)
        self.resize(self.COLLAPSED_WIDTH, self.height())
        self._refresh_style()
        self.collapse_toggled.emit(True)

    def _expand(self) -> None:
        self._collapsed = False
        self.setProperty("collapsed", False)
        self._toolbar_details.show()
        self.tabs.show()
        self.placeholder_panel.show()
        self._btn_toggle.setText("\u00bb")
        self._btn_toggle.setToolTip("Collapse editor panel")
        self._toolbar.setFixedHeight(self._toolbar.sizeHint().height())
        self.setMinimumWidth(self.EXPANDED_MIN_WIDTH)
        self.setMaximumWidth(16777215)
        self._refresh_style()
        self.collapse_toggled.emit(False)

    def _refresh_style(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def _on_text_changed(self) -> None:
        self._update_button_states()
        self.placeholder_panel.refresh_from_text(
            self.yaml_edit.toPlainText() or "",
            self.json_edit.toPlainText() or "",
        )

    def _active_editor(self) -> QPlainTextEdit:
        return self.yaml_edit if self.tabs.currentIndex() == 0 else self.json_edit

    def _update_button_states(self) -> None:
        has_yaml = bool((self.yaml_edit.toPlainText() or "").strip())
        has_json = bool((self.json_edit.toPlainText() or "").strip())
        self.adapter_btn.setEnabled(has_yaml)
        self.llm_json_btn.setEnabled(has_yaml)
        self.adapter_llm_btn.setEnabled(has_yaml)
        self.save_yaml_btn.setEnabled(has_yaml)
        self.save_json_btn.setEnabled(has_json)
        self.import_nifi_btn.setEnabled(has_json)
        self._update_placeholder_counter()

    def _update_placeholder_counter(self) -> None:
        text = self._active_editor().toPlainText() or ""
        all_matches = _PLACEHOLDER_RE.findall(text)
        total = len(all_matches)
        filled_names = self._store.filled_names()
        unfilled = sum(1 for match in all_matches if match[2:-2] not in filled_names)

        if total == 0:
            self._placeholder_label.setVisible(False)
            self._next_placeholder_btn.setVisible(False)
            return

        if unfilled == 0:
            label_text = f"✓ All {total} placeholder{'s' if total != 1 else ''} filled"
            theme = ThemeManager.get().current
            color = "#4ADE80" if theme == "dark" else "#16A34A"
        else:
            label_text = (
                f"⚠ {unfilled} of {total} placeholder{'s' if total != 1 else ''} unfilled"
            )
            theme = ThemeManager.get().current
            color = "#FB923C" if theme == "dark" else "#C2410C"

        self._placeholder_label.setText(label_text)
        self._placeholder_label.setStyleSheet(
            f"color: {color}; font-weight: bold; padding: 0 4px;"
        )
        self._placeholder_label.setVisible(True)
        self._next_placeholder_btn.setVisible(unfilled > 0)

    def _update_generate_state(self) -> None:
        self._update_button_states()

    def _on_filled_changed(self, filled_names: set) -> None:
        frozen = frozenset(filled_names)
        if self._yaml_hl is not None:
            self._yaml_hl.update_filled(frozen)
        if self._json_hl is not None:
            self._json_hl.update_filled(frozen)
        self._update_placeholder_counter()

    def _goto_next_placeholder(self) -> None:
        editor = self._active_editor()
        text = editor.toPlainText() or ""
        filled_names = self._store.filled_names()
        cursor_pos = editor.textCursor().selectionEnd()

        for start_pos in (cursor_pos, 0):
            for match in _PLACEHOLDER_RE.finditer(text, start_pos):
                name = match.group(0)[2:-2]
                if name not in filled_names:
                    cursor = editor.textCursor()
                    cursor.setPosition(match.start())
                    cursor.setPosition(match.end(), QTextCursor.MoveMode.KeepAnchor)
                    editor.setTextCursor(cursor)
                    editor.setFocus()
                    return

    def _on_generate_clicked(self) -> None:
        self._emit_generate(self.mode_combo.currentIndex())

    def _emit_generate(self, mode: int) -> None:
        yaml_text = (self.yaml_edit.toPlainText() or "").strip()
        if mode not in (1, 2, 3) or not yaml_text:
            return
        self.generate_requested.emit(yaml_text, mode)

    def _on_import_nifi_clicked(self) -> None:
        json_text = (self.json_edit.toPlainText() or "").strip()
        if json_text:
            substituted = self._store.substitute_text(json_text)
            self.import_nifi_requested.emit(substituted)

    def set_yaml_text(self, text: str, switch_to_tab: bool = True) -> None:
        self.yaml_edit.setPlainText(text or "")
        self._update_button_states()
        if switch_to_tab:
            self.tabs.setCurrentWidget(self.yaml_edit)

    def set_json_text(self, text: str, switch_to_tab: bool = True) -> None:
        self.json_edit.setPlainText(text or "")
        self._update_button_states()
        if switch_to_tab:
            self.tabs.setCurrentWidget(self.json_edit)

    def get_yaml_text(self) -> str:
        return (self.yaml_edit.toPlainText() or "").strip()

    def get_yaml_text_substituted(self) -> str:
        return self._store.substitute_text(self.get_yaml_text())

    def get_json_text(self) -> str:
        return (self.json_edit.toPlainText() or "").strip()

    def get_json_text_substituted(self) -> str:
        return self._store.substitute_text(self.get_json_text())
