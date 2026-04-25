from __future__ import annotations

from typing import Any

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.interfaces import BaseAdapter


class PluginManager:
    """
    Простейший менеджер плагинов/адаптеров.
    Сейчас всегда возвращает NiFiAdapter.
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or {}

    def get_adapter(self, target: str | None = None) -> BaseAdapter:
        # target игнорируем, по заданию всегда NiFiAdapter
        return NiFiAdapter()