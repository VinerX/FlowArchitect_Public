from __future__ import annotations

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QPlainTextEdit,
    QComboBox,
    QVBoxLayout,
    QWidget,
)

from src.managers.placeholder_manager import PlaceholderManager
from src.ui.placeholder_panel import PlaceholderPanel
from src.ui.theme_manager import ThemeManager
from src.ui.syntax_highlighter import attach_yaml_highlighter, attach_json_highlighter

_PLACEHOLDER_RE = re.compile(r"\{\{[^}]+\}\}")


class CodeEditor(QWidget):
    generate_requested  = pyqtSignal(str, int)
    save_yaml_requested = pyqtSignal()          # Save PIM YAML to file
    save_json_requested = pyqtSignal()          # Save PSM JSON to file
    import_nifi_requested = pyqtSignal(str)     # Import JSON into NiFi (passes json text)

    # для BaseController._ui()
    run_ui_task_signal = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("editor_panel")

        self._store = PlaceholderManager()

        self.run_ui_task_signal.connect(self._run_ui_task)

        # ── Tabs ───────────────────────────────────────────────────────
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

        self.tabs.addTab(self.yaml_edit, "PIM \u2014 YAML")
        self.tabs.addTab(self.json_edit, "PSM \u2014 NiFi JSON")

        # ── Syntax highlighters ────────────────────────────────────────
        self._yaml_hl = None
        self._json_hl = None
        self._attach_highlighters(ThemeManager.get().current)
        ThemeManager.get().register_on_change(self._on_theme_changed)

        # ── Toolbar widgets ────────────────────────────────────────────
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(
            [
                "Direct: NL \u2192 PSM (LLM)",
                "Adapter: NL \u2192 PIM \u2192 PSM",
                "LLM\u00d72: NL \u2192 PIM \u2192 PSM (LLM)",
                "NL \u2192 PIM \u2192 PSM (Adapter+LLM)",
            ]
        )
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setToolTip("Conversion mode")
        self.mode_combo.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self.adapter_btn = QPushButton("YAML → Adapter JSON", self)
        self.adapter_btn.setObjectName("btn_primary")
        self.adapter_btn.setToolTip("Convert PIM YAML to NiFi JSON with the deterministic adapter")
        self.adapter_btn.setEnabled(False)

        self.llm_json_btn = QPushButton("YAML → LLM JSON", self)
        self.llm_json_btn.setToolTip("Convert PIM YAML to NiFi JSON with the configured LLM provider")
        self.llm_json_btn.setEnabled(False)

        self.adapter_llm_btn = QPushButton("Adapter JSON → Corrector", self)
        self.adapter_llm_btn.setToolTip("Run adapter conversion, then ask the NiFi JSON corrector to fix semantic errors")
        self.adapter_llm_btn.setEnabled(False)

        self.save_yaml_btn = QPushButton("Save YAML", self)
        self.save_yaml_btn.setToolTip("Save PIM (YAML) to file")
        self.save_yaml_btn.setEnabled(False)

        self.save_json_btn = QPushButton("Save JSON", self)
        self.save_json_btn.setToolTip("Save PSM (NiFi JSON) to file")
        self.save_json_btn.setEnabled(False)

        self.import_nifi_btn = QPushButton("\u2192 NiFi", self)
        self.import_nifi_btn.setObjectName("btn_nifi")
        self.import_nifi_btn.setToolTip("Import current PSM JSON into NiFi")
        self.import_nifi_btn.setEnabled(False)

        # ── Placeholder counter & navigation ──────────────────────────
        self._placeholder_label = QLabel("", self)
        self._placeholder_label.setObjectName("placeholder_counter")
        self._placeholder_label.setToolTip(
            "Number of {{PLACEHOLDER}} values that must be filled before deployment"
        )
        self._placeholder_label.setVisible(False)

        self._next_placeholder_btn = QPushButton("\u2193 Next", self)
        self._next_placeholder_btn.setObjectName("btn_next_placeholder")
        self._next_placeholder_btn.setToolTip("Jump to next placeholder")
        self._next_placeholder_btn.setVisible(False)
        self._next_placeholder_btn.clicked.connect(self._goto_next_placeholder)

        # ── Connections ────────────────────────────────────────────────
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

        # ── Placeholder panel ──────────────────────────────────────────
        self.placeholder_panel = PlaceholderPanel(self)
        self.placeholder_panel.filled_changed.connect(self._on_filled_changed)

        # ── Toolbar layout ─────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setObjectName("editor_toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 0, 10, 0)
        toolbar_layout.setSpacing(6)

        toolbar_layout.addWidget(self.mode_combo)
        toolbar_layout.addWidget(self.adapter_btn)
        toolbar_layout.addWidget(self.llm_json_btn)
        toolbar_layout.addWidget(self.adapter_llm_btn)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self._placeholder_label)
        toolbar_layout.addWidget(self._next_placeholder_btn)
        toolbar_layout.addWidget(self.save_yaml_btn)
        toolbar_layout.addWidget(self.save_json_btn)
        toolbar_layout.addWidget(self.import_nifi_btn)

        # ── Root layout ────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.placeholder_panel)
        self.setLayout(layout)

        self._update_button_states()

    # ------------------------------------------------------------------
    # Syntax highlighters
    # ------------------------------------------------------------------

    def _attach_highlighters(self, theme: str) -> None:
        """Attach (or re-attach) highlighters for the given theme."""
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

    # ------------------------------------------------------------------
    # Thread-safe UI dispatch
    # ------------------------------------------------------------------

    def _run_ui_task(self, fn):
        if callable(fn):
            fn()

    # ------------------------------------------------------------------
    # Text change handling
    # ------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        """Called whenever either editor changes — updates button states,
        counter, and feeds new text into the placeholder panel."""
        self._update_button_states()
        self.placeholder_panel.refresh_from_text(
            self.yaml_edit.toPlainText() or "",
            self.json_edit.toPlainText() or "",
        )

    # ------------------------------------------------------------------
    # Button states & placeholder counter
    # ------------------------------------------------------------------

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
        unfilled = sum(
            1 for m in all_matches
            if m[2:-2] not in filled_names   # strip {{ }}
        )

        if total == 0:
            self._placeholder_label.setVisible(False)
            self._next_placeholder_btn.setVisible(False)
            return

        if unfilled == 0:
            label_text = f"\u2713 All {total} placeholder{'s' if total != 1 else ''} filled"
            theme = ThemeManager.get().current
            color = "#4ADE80" if theme == "dark" else "#16A34A"
        else:
            label_text = f"\u26a0 {unfilled} of {total} placeholder{'s' if total != 1 else ''} unfilled"
            theme = ThemeManager.get().current
            color = "#FB923C" if theme == "dark" else "#C2410C"

        self._placeholder_label.setText(label_text)
        self._placeholder_label.setStyleSheet(
            f"color: {color}; font-weight: bold; padding: 0 4px;"
        )
        self._placeholder_label.setVisible(True)
        self._next_placeholder_btn.setVisible(unfilled > 0)

    # keep old name as alias so existing connections still work
    def _update_generate_state(self) -> None:
        self._update_button_states()

    # ------------------------------------------------------------------
    # Placeholder fill-state updates (from panel)
    # ------------------------------------------------------------------

    def _on_filled_changed(self, filled_names: set) -> None:
        """Called when the panel fills/clears a placeholder value."""
        fn = frozenset(filled_names)
        if self._yaml_hl is not None:
            self._yaml_hl.update_filled(fn)
        if self._json_hl is not None:
            self._json_hl.update_filled(fn)
        self._update_placeholder_counter()

    # ------------------------------------------------------------------
    # Placeholder navigation
    # ------------------------------------------------------------------

    def _goto_next_placeholder(self) -> None:
        """Jump cursor to the next unfilled {{PLACEHOLDER}} in the active editor."""
        editor = self._active_editor()
        text = editor.toPlainText() or ""
        filled_names = self._store.filled_names()
        cursor_pos = editor.textCursor().selectionEnd()

        # Find next unfilled placeholder after current cursor, then wrap
        for start_pos in (cursor_pos, 0):
            for m in _PLACEHOLDER_RE.finditer(text, start_pos):
                name = m.group(0)[2:-2]          # strip {{ }}
                if name not in filled_names:
                    c = editor.textCursor()
                    c.setPosition(m.start())
                    c.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
                    editor.setTextCursor(c)
                    editor.setFocus()
                    return

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_generate_clicked(self) -> None:
        self._emit_generate(self.mode_combo.currentIndex())

    def _emit_generate(self, mode: int) -> None:
        yaml_text = (self.yaml_edit.toPlainText() or "").strip()
        if mode not in (1, 2, 3) or not yaml_text:
            return
        self.generate_requested.emit(yaml_text, mode)

    def _on_import_nifi_clicked(self) -> None:
        """Substitute placeholder values before sending to NiFi."""
        json_text = (self.json_edit.toPlainText() or "").strip()
        if json_text:
            substituted = self._store.substitute_text(json_text)
            self.import_nifi_requested.emit(substituted)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Return raw PIM YAML text (with {{PLACEHOLDER}} tokens intact)."""
        return (self.yaml_edit.toPlainText() or "").strip()

    def get_yaml_text_substituted(self) -> str:
        """Return PIM YAML with all filled placeholder values substituted."""
        return self._store.substitute_text(self.get_yaml_text())

    def get_json_text(self) -> str:
        """Return raw PSM JSON text (with {{PLACEHOLDER}} tokens intact)."""
        return (self.json_edit.toPlainText() or "").strip()

    def get_json_text_substituted(self) -> str:
        """Return PSM JSON with all filled placeholder values substituted."""
        return self._store.substitute_text(self.get_json_text())
