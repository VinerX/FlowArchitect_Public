from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.chat_widget import ChatWidget
from src.ui.code_editor import CodeEditor
from src.ui.history_panel import HistoryPanel
from src.ui.settings_dialog import SettingsDialog
from src.ui.theme_manager import ThemeManager
from src.core.events import get_event_bus, Events
from src.managers.settings_manager import SettingsManager

# Unicode symbols for theme toggle
_ICON_DARK  = "\u2600"   # ☀  sun  — shown in dark mode (click → go light)
_ICON_LIGHT = "\u25d1"   # ◑  half-circle — shown in light mode (click → go dark)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlowArchitect")
        self.resize(1440, 860)

        self.history_panel = HistoryPanel(self)
        self.chat_widget = ChatWidget(self)
        self.code_editor = CodeEditor(self)
        self.bus = get_event_bus()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("main_splitter")
        splitter.setHandleWidth(6)
        splitter.addWidget(self.history_panel)
        splitter.addWidget(self.chat_widget)
        splitter.addWidget(self.code_editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        # Prevent chat and editor panels from collapsing to zero width
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_header())
        root_layout.addWidget(splitter, 1)
        self.splitter = splitter

        self.setCentralWidget(root)
        self._history_expanded_width = HistoryPanel.EXPANDED_WIDTH
        self._editor_expanded_width = 420
        self.history_panel.collapse_toggled.connect(self._on_history_panel_toggled)
        self.code_editor.collapse_toggled.connect(self._on_editor_panel_toggled)

        # ── Status bar ──────────────────────────────────────────────
        sb = self.statusBar()
        sb.showMessage("Ready")

        self._btn_theme = QToolButton()
        self._btn_theme.clicked.connect(self._on_toggle_theme)
        sb.addPermanentWidget(self._btn_theme)

        tm = ThemeManager.get()
        tm.register_on_change(self._on_theme_changed)
        self._update_theme_btn(tm.current)
        self.bus.subscribe(Events.Settings.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self._refresh_stage_provider_button()

    def _chat_min_width(self) -> int:
        return max(self.chat_widget.minimumWidth(), 360)

    def _on_history_panel_toggled(self, collapsed: bool) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) != 3:
            return

        target = self.history_panel.COLLAPSED_WIDTH if collapsed else max(
            self._history_expanded_width, self.history_panel.EXPANDED_WIDTH
        )
        if collapsed and sizes[0] > self.history_panel.COLLAPSED_WIDTH:
            self._history_expanded_width = sizes[0]
        elif not collapsed:
            available = sizes[0] + max(0, sizes[1] - self._chat_min_width())
            target = min(target, max(self.history_panel.EXPANDED_WIDTH, available))

        delta = target - sizes[0]
        sizes[0] = target
        sizes[1] = max(self._chat_min_width(), sizes[1] - delta)
        self.splitter.setSizes(sizes)

    def _on_editor_panel_toggled(self, collapsed: bool) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) != 3:
            return

        target = self.code_editor.COLLAPSED_WIDTH if collapsed else max(
            self._editor_expanded_width, self.code_editor.EXPANDED_MIN_WIDTH
        )
        if collapsed and sizes[2] > self.code_editor.COLLAPSED_WIDTH:
            self._editor_expanded_width = sizes[2]
        elif not collapsed:
            available = sizes[2] + max(0, sizes[1] - self._chat_min_width())
            target = min(target, max(self.code_editor.EXPANDED_MIN_WIDTH, available))

        delta = target - sizes[2]
        sizes[2] = target
        sizes[1] = max(self._chat_min_width(), sizes[1] - delta)
        self.splitter.setSizes(sizes)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        title = QLabel("FlowArchitect")
        title.setObjectName("app_title")
        layout.addWidget(title)

        subtitle = QLabel("ETL Flow Generator")
        subtitle.setObjectName("app_subtitle")
        layout.addWidget(subtitle)

        layout.addStretch()

        self.stage_provider_btn = QPushButton("", header)
        self.stage_provider_btn.setObjectName("stage_provider_btn")
        self.stage_provider_btn.setToolTip("Current main provider. Click to configure providers for all LLM stages.")
        self.stage_provider_btn.clicked.connect(self._open_stage_providers)
        layout.addWidget(self.stage_provider_btn)

        settings_btn = QToolButton()
        settings_btn.setObjectName("btn_settings")
        settings_btn.setText("\u2699")
        settings_btn.setToolTip("Settings (LLM providers, NiFi connection)")
        settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(settings_btn)

        return header

    def _on_setting_changed(self, *_args, **_kwargs) -> None:
        self._refresh_stage_provider_button()

    def _preset_label(self, preset_id, fallback: str) -> str:
        if not isinstance(preset_id, int) or preset_id <= 0:
            return fallback
        try:
            res = self.bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL, {"id": preset_id}, timeout=0.5)
            preset = res[0] if res else None
            if isinstance(preset, dict):
                name = str(preset.get("name") or f"ID {preset_id}")
                model = str(preset.get("default_model") or "")
                return f"{name}: {model}" if model else name
        except Exception:
            pass
        return f"ID {preset_id}"

    def _refresh_stage_provider_button(self) -> None:
        if not hasattr(self, "stage_provider_btn"):
            return
        sm = SettingsManager()
        active = self._preset_label(sm.get("LAST_API_PRESET_ID"), "active")
        pim = self._preset_label(sm.get("LLM_STAGE_PIM_PRESET_ID"), active)
        err = self._preset_label(sm.get("LLM_STAGE_ERROR_CORRECTOR_PRESET_ID"), active)
        nifi = self._preset_label(sm.get("LLM_STAGE_NIFI_CORRECTOR_PRESET_ID"), active)
        same = pim == err == nifi
        self.stage_provider_btn.setText(f"Provider: {pim}" if same else f"Provider: {pim} + stage overrides")
        self.stage_provider_btn.setToolTip(f"PIM: {pim}\nPIM fix: {err}\nJSON fix: {nifi}")

    def _open_stage_providers(self) -> None:
        dlg = StageProvidersDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh_stage_provider_button()

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Theme toggle (status bar button)
    # ------------------------------------------------------------------

    def _on_toggle_theme(self) -> None:
        ThemeManager.get().toggle()

    def _on_theme_changed(self, theme_name: str) -> None:
        self._update_theme_btn(theme_name)

    def _update_theme_btn(self, theme_name: str) -> None:
        is_dark = theme_name == "dark"
        hover_bg = "rgba(255,255,255,0.12)" if is_dark else "rgba(0,0,0,0.10)"
        self._btn_theme.setStyleSheet(
            "QToolButton { font-size: 16px; background: transparent; border: none; "
            "padding: 2px 8px; }"
            f"QToolButton:hover {{ background: {hover_bg}; border-radius: 4px; }}"
        )
        self._btn_theme.setText(_ICON_DARK if is_dark else _ICON_LIGHT)
        self._btn_theme.setToolTip(
            "Switch to light theme" if is_dark else "Switch to dark theme"
        )


class StageProvidersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stage Providers")
        self.resize(560, 220)
        self.bus = get_event_bus()
        self.settings = SettingsManager()

        self.combo_main = QComboBox(self)
        self.combo_pim = QComboBox(self)
        self.combo_error = QComboBox(self)
        self.combo_nifi = QComboBox(self)
        for combo in (self.combo_main, self.combo_pim, self.combo_error, self.combo_nifi):
            self._populate_presets(combo)

        self._set_combo(self.combo_main, self.settings.get("LAST_API_PRESET_ID"))
        self._set_combo(self.combo_pim, self.settings.get("LLM_STAGE_PIM_PRESET_ID"))
        self._set_combo(self.combo_error, self.settings.get("LLM_STAGE_ERROR_CORRECTOR_PRESET_ID"))
        self._set_combo(self.combo_nifi, self.settings.get("LLM_STAGE_NIFI_CORRECTOR_PRESET_ID"))

        self.combo_main.currentIndexChanged.connect(self._on_main_changed)

        form = QFormLayout()
        form.addRow("Main provider:", self.combo_main)
        form.addRow("PIM architect:", self.combo_pim)
        form.addRow("PIM error corrector:", self.combo_error)
        form.addRow("NiFi JSON corrector:", self.combo_nifi)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _populate_presets(self, combo: QComboBox) -> None:
        combo.clear()
        res = self.bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        meta = res[0] if res else None
        for bucket in ("custom", "builtin"):
            for item in (meta or {}).get(bucket, []) or []:
                pid = getattr(item, "id", None)
                name = getattr(item, "name", "Preset")
                if isinstance(pid, int):
                    combo.addItem(f"{name} (ID {pid})", pid)

    def _set_combo(self, combo: QComboBox, value) -> None:
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return
        if combo.count():
            combo.setCurrentIndex(0)

    def _on_main_changed(self) -> None:
        pid = self.combo_main.currentData()
        for combo in (self.combo_pim, self.combo_error, self.combo_nifi):
            self._set_combo(combo, pid)

    def _save(self) -> None:
        self.settings.set("LAST_API_PRESET_ID", self.combo_main.currentData())
        self.settings.set("LLM_STAGE_PIM_PRESET_ID", self.combo_pim.currentData())
        self.settings.set("LLM_STAGE_ERROR_CORRECTOR_PRESET_ID", self.combo_error.currentData())
        self.settings.set("LLM_STAGE_NIFI_CORRECTOR_PRESET_ID", self.combo_nifi.currentData())
        self.accept()
