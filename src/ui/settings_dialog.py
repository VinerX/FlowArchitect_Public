from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import requests
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QLineEdit,
    QPlainTextEdit,
    QFormLayout,
    QMessageBox,
    QDialogButtonBox,
    QCheckBox,
    QGroupBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from src.core.events import get_event_bus, Events
from src.managers.api_preset_manager import ensure_api_presets_manager
from src.managers.settings_manager import SettingsManager


_PROVIDER_TEMPLATES = [
    {"id": "custom",     "name": "Custom (no template)",
     "url": "",                                                     "protocol_id": "openai_http",     "protocol_overrides": {}},
    {"id": "openai",     "name": "OpenAI",
     "url": "https://api.openai.com/v1/chat/completions",           "protocol_id": "openai_http",     "protocol_overrides": {}},
    {"id": "openrouter", "name": "OpenRouter",
     "url": "https://openrouter.ai/api/v1/chat/completions",        "protocol_id": "openai_http",
     "protocol_overrides": {"headers": {"HTTP-Referer": "https://github.com/VinerX/FlowArchitect", "X-Title": "FlowArchitect"}}},
    {"id": "deepseek",   "name": "DeepSeek",
     "url": "https://api.deepseek.com/chat/completions",            "protocol_id": "openai_http",     "protocol_overrides": {}},
    {"id": "ollama",     "name": "Ollama (local)",
     "url": "http://localhost:11434/v1/chat/completions",           "protocol_id": "openai_http",     "protocol_overrides": {}},
    {"id": "mistral",    "name": "Mistral AI",
     "url": "https://api.mistral.ai/v1/chat/completions",           "protocol_id": "mistral_default", "protocol_overrides": {}},
    {"id": "groq",       "name": "Groq",
     "url": "https://api.groq.com/openai/v1/chat/completions",      "protocol_id": "openai_http",     "protocol_overrides": {}},
    {"id": "together",   "name": "Together AI",
     "url": "https://api.together.xyz/v1/chat/completions",         "protocol_id": "openai_http",     "protocol_overrides": {}},
]


def _set_combo_by_data(combo: QComboBox, value: str, fallback_index: int = 0) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return
    combo.setCurrentIndex(fallback_index)


def _safe_json(text: str, default):
    t = (text or "").strip()
    if not t:
        return default
    try:
        return json.loads(t)
    except Exception:
        return default


def _set_combo_by_int_data(combo: QComboBox, value: Any) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return
    if combo.count():
        combo.setCurrentIndex(0)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(900, 600)

        # гарантируем, что есть подписчики на ApiPresets события
        ensure_api_presets_manager()

        self.bus = get_event_bus()

        self.tabs = QTabWidget(self)

        # --- Provider tab
        self.provider_tab = QWidget(self)
        self.tabs.addTab(self.provider_tab, "Provider")

        self._build_provider_tab()

        # --- NiFi tab
        self.nifi_tab = QWidget(self)
        self.tabs.addTab(self.nifi_tab, "NiFi")

        self._build_nifi_tab()

        # --- Generation tab
        self.generation_tab = QWidget(self)
        self.tabs.addTab(self.generation_tab, "Generation")

        self._build_generation_tab()

        # buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(self._on_ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(self.tabs, 1)
        root.addWidget(self.buttons, 0)
        self.setLayout(root)

        self._reload_presets()
        self._select_current_preset()

    # -----------------------------
    # UI build
    # -----------------------------

    def _build_provider_tab(self):
        layout = QVBoxLayout(self.provider_tab)

        # top row: preset selector
        top = QHBoxLayout()
        top.addWidget(QLabel("Preset:", self.provider_tab))

        self.preset_combo = QComboBox(self.provider_tab)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        top.addWidget(self.preset_combo, 1)

        self.btn_new = QPushButton("New", self.provider_tab)
        self.btn_dup = QPushButton("Duplicate", self.provider_tab)
        self.btn_del = QPushButton("Delete", self.provider_tab)
        self.btn_make_current = QPushButton("Make active", self.provider_tab)

        self.btn_new.clicked.connect(self._on_new)
        self.btn_dup.clicked.connect(self._on_duplicate)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_make_current.clicked.connect(self._on_make_current)

        top.addWidget(self.btn_new)
        top.addWidget(self.btn_dup)
        top.addWidget(self.btn_del)
        top.addWidget(self.btn_make_current)

        layout.addLayout(top)

        # form
        form_box = QGroupBox("Provider settings", self.provider_tab)
        form = QFormLayout(form_box)

        self.edit_id = QLineEdit(form_box)
        self.edit_id.setReadOnly(True)
        form.addRow("ID:", self.edit_id)

        self.combo_template = QComboBox(form_box)
        self._populate_template_combo()
        self.combo_template.currentIndexChanged.connect(self._on_template_changed)
        form.addRow("Template:", self.combo_template)

        self.edit_name = QLineEdit(form_box)
        form.addRow("Name:", self.edit_name)

        self.combo_protocol = QComboBox(form_box)
        self._populate_protocol_combo()
        form.addRow("protocol_id:", self.combo_protocol)

        self.edit_url = QLineEdit(form_box)
        self.edit_url.setPlaceholderText("https://.../v1/chat/completions")
        form.addRow("URL:", self.edit_url)

        model_row = QHBoxLayout()
        self.edit_model = QLineEdit(form_box)
        self.edit_model.setPlaceholderText("gpt-4o-mini / deepseek-chat / llama3.1 ...")
        self.btn_fetch_models = QPushButton("Fetch models", form_box)
        self.btn_fetch_models.setToolTip(
            "Fetch available models from OpenRouter API using the key above"
        )
        self.btn_fetch_models.clicked.connect(self._on_fetch_openrouter_models)
        model_row.addWidget(self.edit_model, 1)
        model_row.addWidget(self.btn_fetch_models)
        form.addRow("Model:", model_row)

        self.edit_key = QLineEdit(form_box)
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API key:", self.edit_key)

        self.chk_show_key = QCheckBox("Show key", form_box)
        self.chk_show_key.stateChanged.connect(self._on_toggle_key_visibility)
        form.addRow("", self.chk_show_key)

        self.edit_reserve_keys = QPlainTextEdit(form_box)
        self.edit_reserve_keys.setPlaceholderText("One key per line (optional)")
        self.edit_reserve_keys.setMaximumBlockCount(2000)
        form.addRow("Reserve keys:", self.edit_reserve_keys)

        self.edit_headers = QPlainTextEdit(form_box)
        self.edit_headers.setPlaceholderText('{ "X-Custom-Header": "value" }')
        self.edit_headers.setMaximumBlockCount(2000)
        form.addRow("Extra headers (JSON):", self.edit_headers)

        self.edit_price_input = QLineEdit(form_box)
        self.edit_price_input.setPlaceholderText("e.g. 0.15  (USD per 1M input tokens)")
        form.addRow("Price: input ($/1M tokens):", self.edit_price_input)

        self.edit_price_output = QLineEdit(form_box)
        self.edit_price_output.setPlaceholderText("e.g. 0.60  (USD per 1M output tokens)")
        form.addRow("Price: output ($/1M tokens):", self.edit_price_output)

        layout.addWidget(form_box, 1)

        # test row
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("Test (OpenAI-compatible request)", self.provider_tab)
        self.btn_test.clicked.connect(self._on_test)
        test_row.addStretch(1)
        test_row.addWidget(self.btn_test)
        layout.addLayout(test_row)

        self.provider_tab.setLayout(layout)

    # -----------------------------
    # Template helpers
    # -----------------------------

    def _populate_template_combo(self):
        for tmpl in _PROVIDER_TEMPLATES:
            self.combo_template.addItem(tmpl["name"], tmpl["id"])

    def _on_template_changed(self):
        tid = self.combo_template.currentData()
        tmpl = next((t for t in _PROVIDER_TEMPLATES if t["id"] == tid), None)
        if not tmpl or tid == "custom":
            self.edit_url.setReadOnly(False)
            self.edit_url.setStyleSheet("")
            return
        self.edit_url.setText(tmpl["url"])
        self.edit_url.setReadOnly(True)
        self.edit_url.setStyleSheet(
            "QLineEdit[readOnly='true'] { color: palette(mid); background: palette(window); }"
        )
        _set_combo_by_data(self.combo_protocol, tmpl["protocol_id"])
        headers = (tmpl.get("protocol_overrides") or {}).get("headers") or {}
        self.edit_headers.setPlainText(
            json.dumps(headers, ensure_ascii=False, indent=2) if headers else "{}"
        )

    def _apply_url_lock(self, template_id: str) -> None:
        tmpl = next((t for t in _PROVIDER_TEMPLATES if t["id"] == template_id), None)
        locked = tmpl is not None and template_id != "custom"
        self.edit_url.setReadOnly(locked)
        self.edit_url.setStyleSheet(
            "QLineEdit[readOnly='true'] { color: palette(mid); background: palette(window); }"
            if locked else ""
        )

    # -----------------------------
    # Protocol combo helpers
    # -----------------------------

    def _populate_protocol_combo(self):
        from managers.protocol_registry import get_protocol_registry
        known = [("openai_http", "OpenAI HTTP (OpenAI-compatible, default)")]
        try:
            reg = get_protocol_registry()
            for pid, proto in reg._items.items():
                known.append((pid, proto.name))
        except Exception:
            pass
        seen: set = set()
        for pid, name in known:
            if pid in seen:
                continue
            seen.add(pid)
            label = f"{pid}  —  {name}"
            self.combo_protocol.addItem(label, pid)

    # -----------------------------
    # OpenRouter model fetch
    # -----------------------------

    def _on_fetch_openrouter_models(self):
        api_key = self.edit_key.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API key required",
                                "Fill in the API key field before fetching models.")
            return

        self.btn_fetch_models.setEnabled(False)
        self.btn_fetch_models.setText("Fetching…")
        try:
            resp = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if resp.status_code != 200:
                QMessageBox.warning(self, "Fetch failed",
                                    f"HTTP {resp.status_code}\n\n{resp.text[:1000]}")
                return
            data = resp.json().get("data") or []
        except Exception as e:
            QMessageBox.critical(self, "Fetch error", str(e)[:1000])
            return
        finally:
            self.btn_fetch_models.setEnabled(True)
            self.btn_fetch_models.setText("Fetch models")

        dlg = _ModelPickerDialog(data, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        model_id, price_in, price_out = dlg.selected_model, dlg.price_in, dlg.price_out
        if model_id:
            self.edit_model.setText(model_id)
        if price_in is not None:
            self.edit_price_input.setText(f"{price_in:.6f}".rstrip("0").rstrip(".") or "0")
        if price_out is not None:
            self.edit_price_output.setText(f"{price_out:.6f}".rstrip("0").rstrip(".") or "0")

    # -----------------------------
    # Presets load/save via events
    # -----------------------------

    def _reload_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()

        res = self.bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        meta = res[0] if res else None
        builtin = (meta or {}).get("builtin", []) or []
        custom = (meta or {}).get("custom", []) or []

        # отображаем красиво, но сохраняем id в itemData
        for m in builtin:
            name = getattr(m, "name", "Builtin")
            pid = getattr(m, "id", None)
            if isinstance(pid, int):
                self.preset_combo.addItem(f"{name} (builtin)", pid)

        for m in custom:
            name = getattr(m, "name", "Custom")
            pid = getattr(m, "id", None)
            if isinstance(pid, int):
                self.preset_combo.addItem(f"{name}", pid)

        self.preset_combo.blockSignals(False)

        if self.preset_combo.count() > 0 and self.preset_combo.currentIndex() < 0:
            self.preset_combo.setCurrentIndex(0)

    def _select_current_preset(self):
        res = self.bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=1.0)
        cur = res[0] if res else None
        if not isinstance(cur, int):
            return

        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == cur:
                self.preset_combo.setCurrentIndex(i)
                return

        # если текущий не найден — просто загрузим первый
        if self.preset_combo.count() > 0:
            self.preset_combo.setCurrentIndex(0)

    def _load_preset_full(self, preset_id: int) -> Optional[Dict[str, Any]]:
        res = self.bus.emit_and_wait(Events.ApiPresets.GET_PRESET_FULL, {"id": int(preset_id)}, timeout=1.0)
        preset = res[0] if res else None
        return preset if isinstance(preset, dict) else None

    def _fill_form(self, preset: Dict[str, Any]):
        self.edit_id.setText(str(preset.get("id", "")))
        self.edit_name.setText(str(preset.get("name", "") or ""))

        # Template: set combo without triggering _on_template_changed
        tid = preset.get("template_id") or "custom"
        self.combo_template.blockSignals(True)
        _set_combo_by_data(self.combo_template, tid)
        self.combo_template.blockSignals(False)
        self._apply_url_lock(tid)

        _set_combo_by_data(self.combo_protocol, str(preset.get("protocol_id", "") or "openai_http"))
        self.edit_url.setText(str(preset.get("url", "") or preset.get("url_tpl", "") or ""))
        self.edit_model.setText(str(preset.get("default_model", "") or ""))
        self.edit_key.setText(str(preset.get("key", "") or ""))

        reserve = preset.get("reserve_keys", []) or []
        if not isinstance(reserve, list):
            reserve = []
        self.edit_reserve_keys.setPlainText("\n".join([str(x) for x in reserve if str(x).strip()]))

        proto_over = preset.get("protocol_overrides", {}) or {}
        headers = (proto_over.get("headers") if isinstance(proto_over, dict) else {}) or {}
        if not isinstance(headers, dict):
            headers = {}
        self.edit_headers.setPlainText(json.dumps(headers, ensure_ascii=False, indent=2))

        self.edit_price_input.setText(str(preset.get("price_input_per_1m") or ""))
        self.edit_price_output.setText(str(preset.get("price_output_per_1m") or ""))

    def _collect_form(self) -> Tuple[Optional[int], Dict[str, Any]]:
        pid_txt = (self.edit_id.text() or "").strip()
        pid = int(pid_txt) if pid_txt.isdigit() else None

        name = (self.edit_name.text() or "").strip() or "Custom"
        template_id = self.combo_template.currentData() or "custom"
        protocol_id = self.combo_protocol.currentData() or "openai_http"
        url = (self.edit_url.text() or "").strip()
        model = (self.edit_model.text() or "").strip()
        key = (self.edit_key.text() or "").strip()

        reserve_keys = []
        for line in (self.edit_reserve_keys.toPlainText() or "").splitlines():
            s = line.strip()
            if s:
                reserve_keys.append(s)

        headers = _safe_json(self.edit_headers.toPlainText(), default={})
        if not isinstance(headers, dict):
            headers = {}

        def _parse_price(text: str) -> Optional[float]:
            t = (text or "").strip().lstrip("$€£").replace(",", ".").strip()
            if not t:
                return None
            try:
                v = float(t)
                return v if v >= 0 else None
            except (ValueError, TypeError):
                return None

        payload = {
            "id": pid,
            "name": name,
            "template_id": template_id,
            "protocol_id": protocol_id,
            "url": url,
            "default_model": model,
            "key": key,
            "reserve_keys": reserve_keys,
            "protocol_overrides": {
                "headers": headers,
            },
            "price_input_per_1m":  _parse_price(self.edit_price_input.text()),
            "price_output_per_1m": _parse_price(self.edit_price_output.text()),
        }
        return pid, payload

    # -----------------------------
    # Handlers
    # -----------------------------

    def _on_preset_changed(self):
        pid = self.preset_combo.currentData()
        if not isinstance(pid, int):
            return
        preset = self._load_preset_full(pid)
        if preset:
            self._fill_form(preset)

    def _on_new(self):
        self.edit_id.setText("")
        _set_combo_by_data(self.combo_template, "custom")
        self.edit_name.setText("Custom")
        _set_combo_by_data(self.combo_protocol, "openai_http")
        self.edit_url.setText("")
        self.edit_url.setReadOnly(False)
        self.edit_url.setStyleSheet("")
        self.edit_model.setText("")
        self.edit_key.setText("")
        self.edit_reserve_keys.setPlainText("")
        self.edit_headers.setPlainText("{}")
        self.edit_price_input.setText("")
        self.edit_price_output.setText("")

    def _on_duplicate(self):
        pid = self.preset_combo.currentData()
        if not isinstance(pid, int):
            return
        preset = self._load_preset_full(pid)
        if not preset:
            return
        preset = dict(preset)
        preset["id"] = None
        preset["name"] = f"{preset.get('name','Preset')} (copy)"
        self._fill_form(preset)
        self.edit_id.setText("")  # новый

    def _on_delete(self):
        pid = self.preset_combo.currentData()
        if not isinstance(pid, int):
            return

        ok = QMessageBox.question(self, "Delete preset", "Delete this preset (or builtin overrides)?") \
             == QMessageBox.StandardButton.Yes
        if not ok:
            return

        self.bus.emit_and_wait(Events.ApiPresets.DELETE_CUSTOM_PRESET, {"id": pid}, timeout=1.0)
        self._reload_presets()
        self._select_current_preset()

    def _on_make_current(self):
        pid = self.preset_combo.currentData()
        if not isinstance(pid, int):
            return
        self.bus.emit_and_wait(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": pid}, timeout=1.0)
        QMessageBox.information(self, "Provider", f"Active preset set to ID={pid}")

    def _on_toggle_key_visibility(self):
        self.edit_key.setEchoMode(
            QLineEdit.EchoMode.Normal if self.chk_show_key.isChecked() else QLineEdit.EchoMode.Password
        )

    def _validate(self, payload: Dict[str, Any]) -> Optional[str]:
        if not (payload.get("name") or "").strip():
            return "Name is empty"
        if not (payload.get("url") or "").strip():
            return "URL is empty"
        if not (payload.get("default_model") or "").strip():
            return "Model is empty"
        return None

    def _on_apply(self) -> bool:
        self._save_nifi_settings()
        self._save_generation_settings()
        _, payload = self._collect_form()
        err = self._validate(payload)
        if err:
            QMessageBox.warning(self, "Validation error", err)
            return False

        res = self.bus.emit_and_wait(Events.ApiPresets.SAVE_CUSTOM_PRESET, payload, timeout=1.0)
        new_id = res[0] if res else None
        if isinstance(new_id, int):
            self.bus.emit_and_wait(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": new_id}, timeout=1.0)
            self._reload_presets()
            # выбрать сохраненный
            for i in range(self.preset_combo.count()):
                if self.preset_combo.itemData(i) == new_id:
                    self.preset_combo.setCurrentIndex(i)
                    break
            QMessageBox.information(self, "Saved", f"Preset saved. Active preset ID={new_id}")
            return True

        QMessageBox.warning(self, "Save failed", "Could not save preset.")
        return False

    def _on_ok(self):
        self._save_nifi_settings()
        self._save_generation_settings()
        if self._on_apply():
            self.accept()


    # -------------------------
    # NiFi tab
    # -------------------------

    def _build_generation_tab(self):
        layout = QVBoxLayout(self.generation_tab)

        stage_box = QGroupBox("Stage providers and timeouts", self.generation_tab)
        stage_form = QFormLayout(stage_box)

        self.combo_pim_preset = QComboBox(stage_box)
        self.combo_psm_preset = QComboBox(stage_box)
        self.combo_error_corrector_preset = QComboBox(stage_box)
        self.combo_nifi_corrector_preset = QComboBox(stage_box)
        for combo in (
            self.combo_pim_preset,
            self.combo_psm_preset,
            self.combo_error_corrector_preset,
            self.combo_nifi_corrector_preset,
        ):
            self._populate_stage_preset_combo(combo)

        self.spin_timeout_default = QSpinBox(stage_box)
        self.spin_timeout_pim = QSpinBox(stage_box)
        self.spin_timeout_psm = QSpinBox(stage_box)
        self.spin_timeout_error_corrector = QSpinBox(stage_box)
        self.spin_timeout_nifi_corrector = QSpinBox(stage_box)
        for spin in (
            self.spin_timeout_default,
            self.spin_timeout_pim,
            self.spin_timeout_psm,
            self.spin_timeout_error_corrector,
            self.spin_timeout_nifi_corrector,
        ):
            spin.setRange(5, 1800)
            spin.setSuffix(" s")

        stage_form.addRow("PIM architect provider:", self.combo_pim_preset)
        stage_form.addRow("PIM timeout:", self.spin_timeout_pim)
        stage_form.addRow("YAML -> JSON provider:", self.combo_psm_preset)
        stage_form.addRow("YAML -> JSON timeout:", self.spin_timeout_psm)
        stage_form.addRow("PIM error corrector provider:", self.combo_error_corrector_preset)
        stage_form.addRow("PIM error corrector timeout:", self.spin_timeout_error_corrector)
        stage_form.addRow("NiFi JSON corrector provider:", self.combo_nifi_corrector_preset)
        stage_form.addRow("NiFi JSON corrector timeout:", self.spin_timeout_nifi_corrector)
        stage_form.addRow("Default timeout:", self.spin_timeout_default)

        layout.addWidget(stage_box)

        correction_box = QGroupBox("Error correction", self.generation_tab)
        correction_form = QFormLayout(correction_box)

        self.chk_error_correction = QCheckBox("Auto-correct PIM validation errors via LLM", correction_box)
        correction_form.addRow("", self.chk_error_correction)

        self.spin_max_retries = QSpinBox(correction_box)
        self.spin_max_retries.setRange(1, 10)
        self.spin_max_retries.setValue(2)
        self.spin_max_retries.setToolTip("Number of LLM retry attempts when validation fails")
        correction_form.addRow("Max retries:", self.spin_max_retries)

        layout.addWidget(correction_box)

        behavior_box = QGroupBox("Generation behavior", self.generation_tab)
        behavior_form = QFormLayout(behavior_box)

        self.chk_always_generate = QCheckBox(
            "Always generate (never ask clarifying questions)", behavior_box
        )
        self.chk_always_generate.setToolTip(
            "When enabled, the LLM will always return a PIM, making reasonable assumptions "
            "instead of asking the user for missing details."
        )
        behavior_form.addRow("", self.chk_always_generate)

        self.chk_suggestions = QCheckBox(
            "Show improvement suggestions after generation", behavior_box
        )
        self.chk_suggestions.setToolTip(
            "After a successful PIM generation the LLM will suggest 2-3 concrete improvements "
            "in the chat (error handling, performance, data quality)."
        )
        behavior_form.addRow("", self.chk_suggestions)

        layout.addWidget(behavior_box)

        nifi_box = QGroupBox("NiFi import", self.generation_tab)
        nifi_form = QFormLayout(nifi_box)

        self.chk_nifi_import_fix = QCheckBox(
            "Auto-fix NiFi validation errors via LLM after import", nifi_box
        )
        self.chk_nifi_import_fix.setToolTip(
            "When enabled, if NiFi reports validation errors after importing the flow, "
            "the LLM is automatically asked to fix the YAML PIM and regenerate."
        )
        nifi_form.addRow("", self.chk_nifi_import_fix)

        layout.addWidget(nifi_box)
        layout.addStretch(1)

        self.generation_tab.setLayout(layout)
        self._load_generation_settings()

    def _populate_stage_preset_combo(self, combo: QComboBox) -> None:
        combo.clear()
        combo.addItem("Use active provider", None)
        res = self.bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        meta = res[0] if res else None
        for bucket in ("custom", "builtin"):
            for m in (meta or {}).get(bucket, []) or []:
                pid = getattr(m, "id", None)
                name = getattr(m, "name", "Preset")
                if isinstance(pid, int):
                    combo.addItem(f"{name} (ID {pid})", pid)

    def _load_generation_settings(self):
        sm = SettingsManager()
        self.chk_error_correction.setChecked(bool(sm.get("LLM_ERROR_CORRECTION_ENABLED", True)))
        self.spin_max_retries.setValue(int(sm.get("LLM_ERROR_CORRECTION_MAX_RETRIES", 2)))
        self.chk_always_generate.setChecked(bool(sm.get("LLM_ALWAYS_GENERATE", False)))
        self.chk_suggestions.setChecked(bool(sm.get("LLM_SUGGESTIONS_ENABLED", False)))
        self.chk_nifi_import_fix.setChecked(bool(sm.get("LLM_NIFI_IMPORT_FIX_ENABLED", False)))
        _set_combo_by_int_data(self.combo_pim_preset, sm.get("LLM_STAGE_PIM_PRESET_ID"))
        _set_combo_by_int_data(self.combo_psm_preset, sm.get("LLM_STAGE_PSM_PRESET_ID"))
        _set_combo_by_int_data(self.combo_error_corrector_preset, sm.get("LLM_STAGE_ERROR_CORRECTOR_PRESET_ID"))
        _set_combo_by_int_data(self.combo_nifi_corrector_preset, sm.get("LLM_STAGE_NIFI_CORRECTOR_PRESET_ID"))
        self.spin_timeout_default.setValue(int(sm.get("LLM_TIMEOUT_DEFAULT_SEC", 45)))
        self.spin_timeout_pim.setValue(int(sm.get("LLM_TIMEOUT_PIM_SEC", 60)))
        self.spin_timeout_psm.setValue(int(sm.get("LLM_TIMEOUT_PSM_SEC", 120)))
        self.spin_timeout_error_corrector.setValue(int(sm.get("LLM_TIMEOUT_ERROR_CORRECTOR_SEC", 240)))
        self.spin_timeout_nifi_corrector.setValue(int(sm.get("LLM_TIMEOUT_NIFI_CORRECTOR_SEC", 300)))

    def _save_generation_settings(self):
        sm = SettingsManager()
        sm.set("LLM_ERROR_CORRECTION_ENABLED", self.chk_error_correction.isChecked())
        sm.set("LLM_ERROR_CORRECTION_MAX_RETRIES", self.spin_max_retries.value())
        sm.set("LLM_ALWAYS_GENERATE", self.chk_always_generate.isChecked())
        sm.set("LLM_SUGGESTIONS_ENABLED", self.chk_suggestions.isChecked())
        sm.set("LLM_NIFI_IMPORT_FIX_ENABLED", self.chk_nifi_import_fix.isChecked())
        sm.set("LLM_STAGE_PIM_PRESET_ID", self.combo_pim_preset.currentData())
        sm.set("LLM_STAGE_PSM_PRESET_ID", self.combo_psm_preset.currentData())
        sm.set("LLM_STAGE_ERROR_CORRECTOR_PRESET_ID", self.combo_error_corrector_preset.currentData())
        sm.set("LLM_STAGE_NIFI_CORRECTOR_PRESET_ID", self.combo_nifi_corrector_preset.currentData())
        sm.set("LLM_TIMEOUT_DEFAULT_SEC", self.spin_timeout_default.value())
        sm.set("LLM_TIMEOUT_PIM_SEC", self.spin_timeout_pim.value())
        sm.set("LLM_TIMEOUT_PSM_SEC", self.spin_timeout_psm.value())
        sm.set("LLM_TIMEOUT_ERROR_CORRECTOR_SEC", self.spin_timeout_error_corrector.value())
        sm.set("LLM_TIMEOUT_NIFI_CORRECTOR_SEC", self.spin_timeout_nifi_corrector.value())
        sm.set("LLM_HTTP_TIMEOUT_SEC", max(
            self.spin_timeout_default.value(),
            self.spin_timeout_pim.value(),
            self.spin_timeout_psm.value(),
            self.spin_timeout_error_corrector.value(),
            self.spin_timeout_nifi_corrector.value(),
        ))

    def _build_nifi_tab(self):
        layout = QVBoxLayout(self.nifi_tab)

        form_box = QGroupBox("NiFi connection settings", self.nifi_tab)
        form = QFormLayout(form_box)

        self.nifi_url = QLineEdit(form_box)
        self.nifi_url.setPlaceholderText("https://localhost:8443")
        form.addRow("URL:", self.nifi_url)

        self.nifi_user = QLineEdit(form_box)
        self.nifi_user.setPlaceholderText("username")
        form.addRow("Username:", self.nifi_user)

        self.nifi_pass = QLineEdit(form_box)
        self.nifi_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.nifi_pass.setPlaceholderText("password")
        form.addRow("Password:", self.nifi_pass)

        self.chk_show_nifi_pass = QCheckBox("Show password", form_box)
        self.chk_show_nifi_pass.stateChanged.connect(self._on_toggle_nifi_pass)
        form.addRow("", self.chk_show_nifi_pass)

        self.chk_nifi_replace_existing = QCheckBox(
            "Replace existing process group when the name matches",
            form_box,
        )
        self.chk_nifi_replace_existing.setToolTip(
            "When enabled, importing a flow deletes the existing root-level NiFi process group "
            "with the same name before creating the new one. Disable to always create a new group."
        )
        form.addRow("", self.chk_nifi_replace_existing)

        layout.addWidget(form_box)
        layout.addStretch(1)

        test_row = QHBoxLayout()
        self.btn_test_nifi = QPushButton("Test NiFi connection", self.nifi_tab)
        self.btn_test_nifi.clicked.connect(self._on_test_nifi)
        test_row.addStretch(1)
        test_row.addWidget(self.btn_test_nifi)
        layout.addLayout(test_row)

        self.nifi_tab.setLayout(layout)
        self._load_nifi_settings()

    def _load_nifi_settings(self):
        sm = SettingsManager()
        self.nifi_url.setText(sm.get("nifi_url", "https://localhost:8443"))
        self.nifi_user.setText(sm.get("nifi_username", ""))
        self.nifi_pass.setText(sm.get("nifi_password", ""))
        self.chk_nifi_replace_existing.setChecked(bool(sm.get("nifi_replace_existing_by_name", True)))

    def _save_nifi_settings(self):
        sm = SettingsManager()
        sm.set("nifi_url",      self.nifi_url.text().strip())
        sm.set("nifi_username", self.nifi_user.text().strip())
        sm.set("nifi_password", self.nifi_pass.text())
        sm.set("nifi_replace_existing_by_name", self.chk_nifi_replace_existing.isChecked())

    def _on_toggle_nifi_pass(self):
        self.nifi_pass.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self.chk_show_nifi_pass.isChecked()
            else QLineEdit.EchoMode.Password
        )

    def _on_test_nifi(self):
        from src.services.nifi_client import NiFiClient
        url  = self.nifi_url.text().strip()
        user = self.nifi_user.text().strip()
        pwd  = self.nifi_pass.text()
        if not url or not user:
            QMessageBox.warning(self, "NiFi", "Fill in URL and Username.")
            return
        self.btn_test_nifi.setEnabled(False)
        self.btn_test_nifi.setText("Connecting...")
        try:
            client = NiFiClient(url, user, pwd)
            ok, msg = client.test_connection()
            if ok:
                QMessageBox.information(self, "NiFi", f"Connected! {msg}")
            else:
                QMessageBox.warning(self, "NiFi", f"Failed: {msg}")
        finally:
            self.btn_test_nifi.setEnabled(True)
            self.btn_test_nifi.setText("Test NiFi connection")

    def _on_test(self):
        _, payload = self._collect_form()
        err = self._validate(payload)
        if err:
            QMessageBox.warning(self, "Validation error", err)
            return

        url = payload["url"]
        api_key = payload.get("key", "")
        model = payload["default_model"]
        headers = (payload.get("protocol_overrides", {}) or {}).get("headers", {}) or {}

        req_headers = {"Content-Type": "application/json"}
        req_headers.update({str(k): str(v) for k, v in headers.items() if k and v is not None})
        if api_key:
            req_headers["Authorization"] = f"Bearer {api_key}"

        test_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Say 'OK' if you can read this."}],
        }

        try:
            r = requests.post(url, headers=req_headers, json=test_payload, timeout=20)
            if r.status_code != 200:
                QMessageBox.warning(self, "Test failed", f"HTTP {r.status_code}\n\n{r.text[:2000]}")
                return
            data = r.json()
            msg = (data.get("choices", [{}])[0].get("message") or {}).get("content", "")
            QMessageBox.information(self, "Test OK", (msg or "No content")[:2000])
        except Exception as e:
            QMessageBox.critical(self, "Test error", str(e)[:2000])


class _ModelPickerDialog(QDialog):
    """Pick an OpenRouter model with free/paid tabs, search, and multi-column table."""

    _COLS = ["Model ID", "Name", "Price in ($/1M)", "Price out ($/1M)"]

    def __init__(self, models_data: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenRouter — select model")
        self.resize(860, 560)

        self.selected_model: Optional[str] = None
        self.price_in: Optional[float] = None
        self.price_out: Optional[float] = None

        free: List[Dict[str, Any]] = []
        paid: List[Dict[str, Any]] = []
        for m in models_data:
            arch = m.get("architecture") or {}
            modality = arch.get("modality") or arch.get("input_modalities") or ""
            if isinstance(modality, list) and "text" not in modality:
                continue
            pricing = m.get("pricing") or {}
            try:
                p_in  = float(pricing.get("prompt")     or 0)
                p_out = float(pricing.get("completion") or 0)
            except (ValueError, TypeError):
                p_in = p_out = 0.0
            entry = {
                "id":        m.get("id", ""),
                "name":      m.get("name", m.get("id", "")),
                "price_in":  p_in  * 1_000_000,
                "price_out": p_out * 1_000_000,
            }
            (free if p_in == 0 and p_out == 0 else paid).append(entry)

        free.sort(key=lambda x: x["id"])
        paid.sort(key=lambda x: x["price_in"])

        layout = QVBoxLayout(self)

        # Search bar
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:", self))
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("filter by model id or name…")
        self._search.textChanged.connect(self._on_search)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)

        self._tabs = QTabWidget(self)
        self._tbl_free = self._make_table(free)
        self._tbl_paid = self._make_table(paid)
        self._tabs.addTab(self._tbl_free, f"Free  ({len(free)})")
        self._tabs.addTab(self._tbl_paid, f"Paid  ({len(paid)})")
        layout.addWidget(self._tabs, 1)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._tbl_free.cellDoubleClicked.connect(lambda *_: self._on_accept())
        self._tbl_paid.cellDoubleClicked.connect(lambda *_: self._on_accept())

    def _make_table(self, entries: List[Dict[str, Any]]) -> QTableWidget:
        tbl = QTableWidget(len(entries), len(self._COLS), self)
        tbl.setObjectName("model_picker_table")
        tbl.setHorizontalHeaderLabels(self._COLS)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setAlternatingRowColors(True)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setVisible(False)
        for row, e in enumerate(entries):
            p_in  = e["price_in"]
            p_out = e["price_out"]
            vals = [
                e["id"],
                e["name"],
                f"${p_in:.4f}"  if p_in  else "free",
                f"${p_out:.4f}" if p_out else "free",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, e)
                tbl.setItem(row, col, item)
        return tbl

    def _on_search(self, text: str) -> None:
        needle = text.strip().lower()
        for tbl in (self._tbl_free, self._tbl_paid):
            for row in range(tbl.rowCount()):
                item = tbl.item(row, 0)
                if item is None:
                    continue
                entry = item.data(Qt.ItemDataRole.UserRole) or {}
                visible = (not needle
                           or needle in entry.get("id", "").lower()
                           or needle in entry.get("name", "").lower())
                tbl.setRowHidden(row, not visible)

    def _current_entry(self) -> Optional[Dict[str, Any]]:
        tbl = self._tbl_free if self._tabs.currentIndex() == 0 else self._tbl_paid
        row = tbl.currentRow()
        if row < 0:
            return None
        item = tbl.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_accept(self):
        entry = self._current_entry()
        if not entry:
            QMessageBox.warning(self, "No selection", "Select a model first.")
            return
        self.selected_model = entry["id"]
        self.price_in  = entry["price_in"]
        self.price_out = entry["price_out"]
        self.accept()
