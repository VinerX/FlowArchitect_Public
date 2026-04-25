import json
import os
from typing import Any
from src.core.events import get_event_bus, Events
from main_logger import logger


class SettingsManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SettingsManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = "config/settings.json"):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.config_path = config_path
        self.settings: dict = {}
        self.event_bus = get_event_bus()
        self.load()
        self._initialized = True

    def load(self):
        """Загружает настройки из файла"""
        if not os.path.exists(self.config_path):
            logger.warning(f"Settings file not found at {self.config_path}, creating default.")
            self.save()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.settings = json.load(f)
            logger.info("Settings loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            self.settings = {}

    def save(self):
        """Сохраняет настройки в файл"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Метод для совместимости со старым кодом.
        Позволяет обращаться как settings.get("KEY")
        """
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        """Устанавливает значение и эмитит событие"""
        old_value = self.settings.get(key)
        if old_value == value:
            return

        self.settings[key] = value
        self.save()

        # Уведомляем систему (например, LLMEngine может обновить конфиг)
        self.event_bus.emit(Events.Settings.SETTING_CHANGED, {"key": key, "value": value})

    # Dunder methods для доступа как к словарю (settings["KEY"])
    def __getitem__(self, item):
        return self.settings.get(item)

    def __setitem__(self, key, value):
        self.set(key, value)