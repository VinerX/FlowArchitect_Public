from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from main_logger import logger
from src.core.events import Events, get_event_bus
from src.managers.settings_manager import SettingsManager


@dataclass
class PresetMeta:
    id: int
    name: str
    builtin: bool = False


class ApiPresetsManager:
    """
    Lightweight preset storage over SettingsManager + EventBus.
    Builtins are fixed for the public thesis demo; custom presets stay optional.
    """

    SETTINGS_CUSTOM_KEY = "API_PRESETS_CUSTOM"
    SETTINGS_BUILTIN_OVERRIDES_KEY = "API_PRESETS_BUILTIN_OVERRIDES"
    SETTINGS_LAST_ID_KEY = "LAST_API_PRESET_ID"

    def __init__(self, settings: SettingsManager):
        self.settings = settings
        self.bus = get_event_bus()

        self.bus.subscribe(Events.ApiPresets.GET_PRESET_LIST, self._on_get_preset_list, weak=False)
        self.bus.subscribe(Events.ApiPresets.GET_PRESET_FULL, self._on_get_preset_full, weak=False)
        self.bus.subscribe(Events.ApiPresets.SAVE_CUSTOM_PRESET, self._on_save_custom_preset, weak=False)
        self.bus.subscribe(Events.ApiPresets.DELETE_CUSTOM_PRESET, self._on_delete_custom_preset, weak=False)
        self.bus.subscribe(Events.ApiPresets.GET_CURRENT_PRESET_ID, self._on_get_current_preset_id, weak=False)
        self.bus.subscribe(Events.ApiPresets.SET_CURRENT_PRESET_ID, self._on_set_current_preset_id, weak=False)

        self._ensure_defaults()

    def _builtin_presets(self) -> List[Dict[str, Any]]:
        openrouter_headers = {
            "headers": {
                "HTTP-Referer": "https://github.com/VinerX/FlowArchitect",
                "X-Title": "FlowArchitect",
            }
        }
        return [
            {
                "id": 1,
                "name": "OpenRouter DeepSeek V4 Pro",
                "protocol_id": "openai_http",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "default_model": "deepseek/deepseek-v4-pro",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": openrouter_headers,
            },
            {
                "id": 2,
                "name": "OpenRouter Qwen 3.6 Plus",
                "protocol_id": "openai_http",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "default_model": "qwen/qwen3.6-plus",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": openrouter_headers,
            },
            {
                "id": 3,
                "name": "OpenRouter Claude Sonnet 4.6",
                "protocol_id": "openai_http",
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "default_model": "anthropic/claude-sonnet-4.6",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": openrouter_headers,
            },
            {
                "id": 4,
                "name": "OpenAI",
                "protocol_id": "openai_http",
                "url": "https://api.openai.com/v1/chat/completions",
                "default_model": "gpt-4o-mini",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {},
            },
            {
                "id": 5,
                "name": "Google Gemini",
                "protocol_id": "google_gemini_default",
                "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                "default_model": "gemini-2.5-flash",
                "key": "",
                "reserve_keys": [],
                "protocol_overrides": {},
            },
        ]

    def _ensure_defaults(self) -> None:
        if not isinstance(self.settings.get(self.SETTINGS_CUSTOM_KEY), list):
            self.settings.set(self.SETTINGS_CUSTOM_KEY, [])
        if not isinstance(self.settings.get(self.SETTINGS_BUILTIN_OVERRIDES_KEY), dict):
            self.settings.set(self.SETTINGS_BUILTIN_OVERRIDES_KEY, {})

        last_id = self.settings.get(self.SETTINGS_LAST_ID_KEY, 0)
        if not isinstance(last_id, int) or last_id <= 0:
            self.settings.set(self.SETTINGS_LAST_ID_KEY, 4)

    def _load_custom(self) -> List[Dict[str, Any]]:
        items = self.settings.get(self.SETTINGS_CUSTOM_KEY, [])
        return items if isinstance(items, list) else []

    def _save_custom(self, items: List[Dict[str, Any]]) -> None:
        self.settings.set(self.SETTINGS_CUSTOM_KEY, items)

    def _load_builtin_overrides(self) -> Dict[str, Dict[str, Any]]:
        data = self.settings.get(self.SETTINGS_BUILTIN_OVERRIDES_KEY, {})
        return data if isinstance(data, dict) else {}

    def _save_builtin_overrides(self, data: Dict[str, Dict[str, Any]]) -> None:
        self.settings.set(self.SETTINGS_BUILTIN_OVERRIDES_KEY, data)

    def _allocate_custom_id(self) -> int:
        custom = self._load_custom()
        used = {int(x.get("id")) for x in custom if isinstance(x, dict) and isinstance(x.get("id"), int)}
        used |= {int(x.get("id")) for x in self._builtin_presets() if isinstance(x.get("id"), int)}
        cid = 1000
        while cid in used:
            cid += 1
        return cid

    def _get_full_by_id(self, preset_id: int) -> Optional[Dict[str, Any]]:
        for builtin in self._builtin_presets():
            if int(builtin.get("id", -1)) == int(preset_id):
                overrides = self._load_builtin_overrides().get(str(preset_id), {}) or {}
                merged = dict(builtin)
                merged.update({k: v for k, v in overrides.items()})
                return merged

        for custom in self._load_custom():
            if isinstance(custom, dict) and int(custom.get("id", -1)) == int(preset_id):
                return custom
        return None

    def _on_get_preset_list(self, event) -> Dict[str, Any]:
        builtin_meta = [PresetMeta(id=int(x["id"]), name=str(x.get("name", "")), builtin=True) for x in self._builtin_presets()]
        custom_meta = []
        for item in self._load_custom():
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                custom_meta.append(PresetMeta(id=int(item["id"]), name=str(item.get("name", "Custom")), builtin=False))
        return {"builtin": builtin_meta, "custom": custom_meta}

    def _on_get_preset_full(self, event) -> Optional[Dict[str, Any]]:
        data = getattr(event, "data", None) or {}
        preset_id = data.get("id")
        if not isinstance(preset_id, int):
            return None
        return self._get_full_by_id(preset_id)

    def _on_save_custom_preset(self, event) -> Optional[int]:
        payload = getattr(event, "data", None) or {}
        if not isinstance(payload, dict):
            return None

        preset_id = payload.get("id")
        name = str(payload.get("name", "") or "Custom").strip()

        if isinstance(preset_id, int) and any(int(b["id"]) == preset_id for b in self._builtin_presets()):
            overrides = self._load_builtin_overrides()
            overrides[str(preset_id)] = {
                "name": name,
                "protocol_id": payload.get("protocol_id", "openai_http"),
                "url": payload.get("url", ""),
                "url_tpl": payload.get("url_tpl", ""),
                "default_model": payload.get("default_model", ""),
                "key": payload.get("key", ""),
                "reserve_keys": payload.get("reserve_keys", []) or [],
                "protocol_overrides": payload.get("protocol_overrides", {}) or {},
                "template_id": payload.get("template_id", "custom"),
                "price_input_per_1m": payload.get("price_input_per_1m"),
                "price_output_per_1m": payload.get("price_output_per_1m"),
            }
            self._save_builtin_overrides(overrides)
            return preset_id

        custom = self._load_custom()
        if not isinstance(preset_id, int):
            preset_id = self._allocate_custom_id()

        out = {
            "id": int(preset_id),
            "name": name,
            "protocol_id": payload.get("protocol_id", "openai_http"),
            "url": payload.get("url", ""),
            "url_tpl": payload.get("url_tpl", ""),
            "default_model": payload.get("default_model", ""),
            "key": payload.get("key", ""),
            "reserve_keys": payload.get("reserve_keys", []) or [],
            "protocol_overrides": payload.get("protocol_overrides", {}) or {},
            "price_input_per_1m": payload.get("price_input_per_1m"),
            "price_output_per_1m": payload.get("price_output_per_1m"),
        }

        replaced = False
        for index, item in enumerate(custom):
            if isinstance(item, dict) and int(item.get("id", -1)) == int(preset_id):
                custom[index] = out
                replaced = True
                break
        if not replaced:
            custom.append(out)

        self._save_custom(custom)
        return int(preset_id)

    def _on_delete_custom_preset(self, event) -> bool:
        data = getattr(event, "data", None) or {}
        preset_id = data.get("id")
        if not isinstance(preset_id, int):
            return False

        if any(int(b["id"]) == preset_id for b in self._builtin_presets()):
            overrides = self._load_builtin_overrides()
            if str(preset_id) in overrides:
                overrides.pop(str(preset_id), None)
                self._save_builtin_overrides(overrides)
            return True

        custom = self._load_custom()
        new_custom = [x for x in custom if not (isinstance(x, dict) and int(x.get("id", -1)) == preset_id)]
        self._save_custom(new_custom)
        return True

    def _on_get_current_preset_id(self, event) -> int:
        preset_id = self.settings.get(self.SETTINGS_LAST_ID_KEY, 4)
        return preset_id if isinstance(preset_id, int) else 4

    def _on_set_current_preset_id(self, event) -> bool:
        data = getattr(event, "data", None) or {}
        preset_id = data.get("id")
        if not isinstance(preset_id, int) or preset_id <= 0:
            return False
        self.settings.set(self.SETTINGS_LAST_ID_KEY, preset_id)
        return True


_api_presets_manager: Optional[ApiPresetsManager] = None


def ensure_api_presets_manager() -> ApiPresetsManager:
    global _api_presets_manager
    if _api_presets_manager is None:
        _api_presets_manager = ApiPresetsManager(SettingsManager())
        logger.info("[ApiPresetsManager] initialized")
    return _api_presets_manager
