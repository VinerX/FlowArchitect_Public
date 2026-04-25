from __future__ import annotations

import json
import threading
from typing import Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.core.events import Events
from src.controllers.base_controller import BaseController
from src.managers.placeholder_manager import PlaceholderManager


def _patch_bundle_versions(flow_json: dict, version: str) -> None:
    """Replace all bundle 'version' fields in flow_json with the actual NiFi version."""
    contents = flow_json.get("flowContents", {})
    for section in ("processors", "controllerServices"):
        for item in contents.get(section, []):
            if "bundle" in item:
                item["bundle"]["version"] = version


class EditorController(BaseController):
    def __init__(self, main_controller: Any, view: Any):
        super().__init__(main_controller, view)

        if self.view is not None:
            if hasattr(self.view, "generate_requested"):
                self.view.generate_requested.connect(self._on_generate_requested)
            if hasattr(self.view, "save_yaml_requested"):
                self.view.save_yaml_requested.connect(self._on_save_yaml)
            if hasattr(self.view, "save_json_requested"):
                self.view.save_json_requested.connect(self._on_save_json)
            if hasattr(self.view, "import_nifi_requested"):
                self.view.import_nifi_requested.connect(self._on_import_nifi)

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Editor.UPDATE_CODE, self._on_update_code, weak=False)

    # ------------------------------------------------------------------
    # Editor.UPDATE_CODE event
    # ------------------------------------------------------------------

    def _on_update_code(self, *args: Any, **kwargs: Any):
        payload = self._extract_payload(*args, **kwargs)
        kind = (payload.get("kind") or "").strip().lower()
        text = payload.get("text") or payload.get("code") or ""

        if kind == "yaml":
            self._ui(lambda: self.view.set_yaml_text(text, switch_to_tab=True))
        elif kind == "json":
            self._ui(lambda: self.view.set_json_text(text, switch_to_tab=True))
        else:
            self._ui(lambda: self.view.set_yaml_text(text, switch_to_tab=False))

    # ------------------------------------------------------------------
    # Conversion button
    # ------------------------------------------------------------------

    def _on_generate_requested(self, yaml_text: str, _mode: int = 1):
        yaml_text = (yaml_text or "").strip()
        if not yaml_text:
            return
        self.event_bus.emit(Events.Etl.REQUEST_CONVERSION, {"yaml": yaml_text, "mode": _mode})

    # ------------------------------------------------------------------
    # Save YAML
    # ------------------------------------------------------------------

    def _on_save_yaml(self):
        from src.managers.settings_manager import SettingsManager
        substitute = SettingsManager().get("placeholder_substitute_yaml_on_save", False)

        if substitute and hasattr(self.view, "get_yaml_text_substituted"):
            text = self.view.get_yaml_text_substituted()
        else:
            text = self.view.get_yaml_text() if hasattr(self.view, "get_yaml_text") else ""

        if not text.strip():
            return

        path, _ = QFileDialog.getSaveFileName(
            self.view, "Save PIM YAML", "flow.yaml",
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            QMessageBox.critical(self.view, "Save failed", str(e))

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------

    def _on_save_json(self):
        # Always substitute placeholder values when saving JSON (deployment artifact)
        if hasattr(self.view, "get_json_text_substituted"):
            text = self.view.get_json_text_substituted()
        else:
            raw = self.view.get_json_text() if hasattr(self.view, "get_json_text") else ""
            text = PlaceholderManager().substitute_text(raw)

        if not text.strip():
            return

        path, _ = QFileDialog.getSaveFileName(
            self.view, "Save PSM JSON", "flow.json",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            QMessageBox.critical(self.view, "Save failed", str(e))

    # ------------------------------------------------------------------
    # Import into NiFi
    # ------------------------------------------------------------------

    def _on_import_nifi(self, json_text: str):
        """Validate JSON, read NiFi settings, import in background thread."""
        from src.managers.settings_manager import SettingsManager
        from src.services.nifi_client import NiFiClient

        # --- parse JSON first ---
        try:
            flow_json = json.loads(json_text)
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self.view, "Import error",
                f"Invalid JSON in PSM tab:\n{e}",
            )
            return

        # --- read settings ---
        sm = SettingsManager()
        url  = sm.get("nifi_url", "").strip()
        user = sm.get("nifi_username", "").strip()
        pwd  = sm.get("nifi_password", "")
        replace_existing = bool(sm.get("nifi_replace_existing_by_name", True))

        if not url or not user:
            QMessageBox.warning(
                self.view, "NiFi not configured",
                "NiFi URL and username are not set.\n\n"
                "Open Settings \u2192 NiFi and fill in the connection details.",
            )
            return

        # --- disable button while running ---
        btn = getattr(self.view, "import_nifi_btn", None)
        if btn:
            self._ui(lambda: btn.setEnabled(False))
            self._ui(lambda: btn.setText("Importing..."))

        def _do_import():
            client = NiFiClient(url, user, pwd)
            nifi_version = client.get_version()
            if nifi_version != "unknown":
                _patch_bundle_versions(flow_json, nifi_version)
            ok, result = client.import_flow(flow_json, replace_if_exists=replace_existing)

            if ok:
                pg_id = result
                validation_errors = client.get_validation_errors(pg_id)
                self.event_bus.emit(
                    Events.NiFi.IMPORT_RESULT,
                    {"ok": True, "pg_id": pg_id, "validation_errors": validation_errors},
                )
            else:
                self.event_bus.emit(
                    Events.NiFi.IMPORT_RESULT,
                    {"ok": False, "error": result, "validation_errors": []},
                )

            def _restore_btn():
                if btn:
                    btn.setEnabled(True)
                    btn.setText("\u2192 NiFi")
                if not ok:
                    QMessageBox.critical(
                        self.view, "Import failed",
                        f"NiFi returned an error:\n\n{result}",
                    )

            self._ui(_restore_btn)

        threading.Thread(target=_do_import, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_payload(*args: Any, **kwargs: Any) -> dict:
        if "payload" in kwargs and isinstance(kwargs["payload"], dict):
            return kwargs["payload"]
        if "data" in kwargs and isinstance(kwargs["data"], dict):
            return kwargs["data"]

        if args:
            first = args[0]
            if hasattr(first, "data") and isinstance(getattr(first, "data"), dict):
                return getattr(first, "data")
            if hasattr(first, "payload") and isinstance(getattr(first, "payload"), dict):
                return getattr(first, "payload")
            if isinstance(first, dict):
                return first

        if len(args) >= 2 and isinstance(args[1], dict):
            return args[1]
        return {}
