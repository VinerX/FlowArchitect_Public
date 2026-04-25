from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from main_logger import logger
from src.core.events import get_event_bus, Events
from src.managers.settings_manager import SettingsManager


@dataclass
class PresetMeta:
    id: int
    name: str
    builtin: bool = False


class ApiPresetsManager:
    """
    Минимальная реализация пресетов поверх SettingsManager + EventBus.
    ApiPresetResolver сможет работать, потому что появляются подписчики на:
      - Events.ApiPresets.GET_PRESET_LIST
      - Events.ApiPresets.GET_PRESET_FULL
    """

    SETTINGS_CUSTOM_KEY = "API_PRESETS_CUSTOM"
    SETTINGS_BUILTIN_OVERRIDES_KEY = "API_PRESETS_BUILTIN_OVERRIDES"
    SETTINGS_LAST_ID_KEY = "LAST_API_PRESET_ID"

    def __init__(self, settings: SettingsManager):
        self.settings = settings
        self.bus = get_event_bus()

        # подписываемся (ВАЖНО: weak=False, чтобы обработчики не умерли)
        self.bus.subscribe(Events.ApiPresets.GET_PRESET_LIST, self._on_get_preset_list, weak=False)
        self.bus.subscribe(Events.ApiPresets.GET_PRESET_FULL, self._on_get_preset_full, weak=False)
        self.bus.subscribe(Events.ApiPresets.SAVE_CUSTOM_PRESET, self._on_save_custom_preset, weak=False)
        self.bus.subscribe(Events.ApiPresets.DELETE_CUSTOM_PRESET, self._on_delete_custom_preset, weak=False)
        self.bus.subscribe(Events.ApiPresets.GET_CURRENT_PRESET_ID, self._on_get_current_preset_id, weak=False)
        self.bus.subscribe(Events.ApiPresets.SET_CURRENT_PRESET_ID, self._on_set_current_preset_id, weak=False)

        self._ensure_defaults()

    # ---------------------------
    # Builtins
    # ---------------------------

    def _builtin_presets(self) -> List[Dict[str, Any]]:
        # Можно расширять список под ваши провайдеры
        return [
            {
                "id": 1,
                "name": "OpenAI",
                "protocol_id": "openai_http",
                "url": "https://api.openai.com/v1/chat/completions",
                "default_model": "gpt-4o-mini",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {},
            },
            {
                "id": 2,
                "name": "DeepSeek (OpenAI-compatible)",
                "protocol_id": "openai_http",
                "url": "https://api.deepseek.com/chat/completions",
                "default_model": "deepseek-chat",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {},
            },
            {
                "id": 3,
                "name": "Ollama (local, OpenAI-compatible)",
                "protocol_id": "openai_http",
                "url": "http://localhost:11434/v1/chat/completions",
                "default_model": "llama3.1",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {},
            },
            {
                "id": 4,
                "name": "OpenRouter",
                "protocol_id": "openai_http",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "default_model": "openai/gpt-4o-mini",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {
                    "headers": {
                        "HTTP-Referer": "https://github.com/VinerX/FlowArchitect",
                        "X-Title": "FlowArchitect",
                    }
                },
            },
        ]

    def _ensure_defaults(self) -> None:
        # гарантируем структуру в settings.json
        if not isinstance(self.settings.get(self.SETTINGS_CUSTOM_KEY), list):
            self.settings.set(self.SETTINGS_CUSTOM_KEY, [])
        if not isinstance(self.settings.get(self.SETTINGS_BUILTIN_OVERRIDES_KEY), dict):
            self.settings.set(self.SETTINGS_BUILTIN_OVERRIDES_KEY, {})

        last_id = self.settings.get(self.SETTINGS_LAST_ID_KEY, 0)
        if not isinstance(last_id, int) or last_id <= 0:
            self.settings.set(self.SETTINGS_LAST_ID_KEY, 1)

    # ---------------------------
    # Storage helpers
    # ---------------------------

    def _load_custom(self) -> List[Dict[str, Any]]:
        items = self.settings.get(self.SETTINGS_CUSTOM_KEY, [])
        return items if isinstance(items, list) else []

    def _save_custom(self, items: List[Dict[str, Any]]) -> None:
        self.settings.set(self.SETTINGS_CUSTOM_KEY, items)

    def _load_builtin_overrides(self) -> Dict[str, Dict[str, Any]]:
        d = self.settings.get(self.SETTINGS_BUILTIN_OVERRIDES_KEY, {})
        return d if isinstance(d, dict) else {}

    def _save_builtin_overrides(self, d: Dict[str, Dict[str, Any]]) -> None:
        self.settings.set(self.SETTINGS_BUILTIN_OVERRIDES_KEY, d)

    def _allocate_custom_id(self) -> int:
        custom = self._load_custom()
        used = {int(x.get("id")) for x in custom if isinstance(x, dict) and isinstance(x.get("id"), int)}
        used |= {int(x.get("id")) for x in self._builtin_presets() if isinstance(x.get("id"), int)}
        cid = 1000
        while cid in used:
            cid += 1
        return cid

    def _get_full_by_id(self, preset_id: int) -> Optional[Dict[str, Any]]:
        # builtin + overrides
        for b in self._builtin_presets():
            if int(b.get("id", -1)) == int(preset_id):
                ov = self._load_builtin_overrides().get(str(preset_id), {}) or {}
                merged = dict(b)
                merged.update({k: v for k, v in ov.items()})
                return merged

        # custom
        for c in self._load_custom():
            if isinstance(c, dict) and int(c.get("id", -1)) == int(preset_id):
                return c
        return None

    # ---------------------------
    # Event handlers
    # ---------------------------

    def _on_get_preset_list(self, event) -> Dict[str, Any]:
        builtin_meta = [PresetMeta(id=int(x["id"]), name=str(x.get("name", "")), builtin=True) for x in self._builtin_presets()]
        custom_meta = []
        for x in self._load_custom():
            if isinstance(x, dict) and isinstance(x.get("id"), int):
                custom_meta.append(PresetMeta(id=int(x["id"]), name=str(x.get("name", "Custom")), builtin=False))

        return {"builtin": builtin_meta, "custom": custom_meta}

    def _on_get_preset_full(self, event) -> Optional[Dict[str, Any]]:
        data = getattr(event, "data", None) or {}
        pid = data.get("id")
        if not isinstance(pid, int):
            return None
        return self._get_full_by_id(pid)

    def _on_save_custom_preset(self, event) -> Optional[int]:
        payload = getattr(event, "data", None) or {}
        if not isinstance(payload, dict):
            return None

        pid = payload.get("id")
        name = str(payload.get("name", "") or "Custom").strip()

        # если это builtin id -> сохраняем OVERRIDES
        if isinstance(pid, int) and any(int(b["id"]) == pid for b in self._builtin_presets()):
            overrides = self._load_builtin_overrides()
            overrides[str(pid)] = {
                "name": name,
                "protocol_id": payload.get("protocol_id", "openai_http"),
                "url": payload.get("url", ""),
                "url_tpl": payload.get("url_tpl", ""),
                "default_model": payload.get("default_model", ""),
                "key": payload.get("key", ""),
                "reserve_keys": payload.get("reserve_keys", []) or [],
                "protocol_overrides": payload.get("protocol_overrides", {}) or {},
                "template_id":         payload.get("template_id", "custom"),
                "price_input_per_1m":  payload.get("price_input_per_1m"),
                "price_output_per_1m": payload.get("price_output_per_1m"),
            }
            self._save_builtin_overrides(overrides)
            return pid

        # иначе custom
        custom = self._load_custom()
        if not isinstance(pid, int):
            pid = self._allocate_custom_id()

        # upsert
        out = {
            "id": int(pid),
            "name": name,
            "protocol_id": payload.get("protocol_id", "openai_http"),
            "url": payload.get("url", ""),
            "url_tpl": payload.get("url_tpl", ""),
            "default_model": payload.get("default_model", ""),
            "key": payload.get("key", ""),
            "reserve_keys": payload.get("reserve_keys", []) or [],
            "protocol_overrides": payload.get("protocol_overrides", {}) or {},
            "price_input_per_1m":  payload.get("price_input_per_1m"),
            "price_output_per_1m": payload.get("price_output_per_1m"),
        }

        replaced = False
        for i, item in enumerate(custom):
            if isinstance(item, dict) and int(item.get("id", -1)) == int(pid):
                custom[i] = out
                replaced = True
                break
        if not replaced:
            custom.append(out)

        self._save_custom(custom)
        return int(pid)

    def _on_delete_custom_preset(self, event) -> bool:
        data = getattr(event, "data", None) or {}
        pid = data.get("id")
        if not isinstance(pid, int):
            return False

        # builtin -> удаляем overrides
        if any(int(b["id"]) == pid for b in self._builtin_presets()):
            overrides = self._load_builtin_overrides()
            if str(pid) in overrides:
                overrides.pop(str(pid), None)
                self._save_builtin_overrides(overrides)
            return True

        # custom -> remove
        custom = self._load_custom()
        new_custom = [x for x in custom if not (isinstance(x, dict) and int(x.get("id", -1)) == pid)]
        self._save_custom(new_custom)
        return True

    def _on_get_current_preset_id(self, event) -> int:
        pid = self.settings.get(self.SETTINGS_LAST_ID_KEY, 1)
        return pid if isinstance(pid, int) else 1

    def _on_set_current_preset_id(self, event) -> bool:
        data = getattr(event, "data", None) or {}
        pid = data.get("id")
        if not isinstance(pid, int) or pid <= 0:
            return False
        self.settings.set(self.SETTINGS_LAST_ID_KEY, pid)
        return True


_api_presets_manager: Optional[ApiPresetsManager] = None


def ensure_api_presets_manager() -> ApiPresetsManager:
    global _api_presets_manager
    if _api_presets_manager is None:
        _api_presets_manager = ApiPresetsManager(SettingsManager())
        logger.info("[ApiPresetsManager] initialized")
    return _api_presets_manager