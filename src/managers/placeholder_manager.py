"""FlowArchitect — PlaceholderManager

Single source of truth for {{PLACEHOLDER}} values across PIM and PSM editors.

Lifecycle:
  - Session entries  : in-memory only; lost when app closes.
  - Global entries   : persisted to ~/.flowarchitect/global_placeholders.json;
                       shared across all projects and sessions.

Auto-sensitive detection (can be disabled via set_auto_mask_enabled(False)):
  Any placeholder whose name contains PASSWORD, SECRET, KEY, TOKEN,
  CREDENTIAL, AUTH, PRIVATE, or PWD is treated as sensitive by default.
  Sensitive entries render their value as ••••• in the UI.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional

from main_logger import logger

# ── Constants ────────────────────────────────────────────────────────────────

_SENSITIVE_PATTERN = re.compile(
    r"(PASSWORD|SECRET|KEY|TOKEN|CREDENTIAL|AUTH|PRIVATE|PWD|PASS)",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")

_GLOBAL_STORE_PATH = os.path.join(
    os.path.expanduser("~"), ".flowarchitect", "global_placeholders.json"
)

# Minimum value length for reverse-masking (avoids false positives on
# very short strings like "1" or "on")
_MIN_MASK_LEN = 4


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class PlaceholderEntry:
    value: str = ""
    is_global: bool = False
    is_sensitive: bool = False    # user-controlled toggle
    auto_sensitive: bool = False  # computed from name pattern

    def is_filled(self) -> bool:
        return bool(self.value.strip())

    def should_mask_in_ui(self) -> bool:
        """Whether the value field should render as ••••• in the UI."""
        return self.is_sensitive or self.auto_sensitive


# ── Manager ──────────────────────────────────────────────────────────────────

class PlaceholderManager:
    """Singleton store for {{PLACEHOLDER}} fill-in values."""

    _instance: Optional["PlaceholderManager"] = None

    def __new__(cls) -> "PlaceholderManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._entries: Dict[str, PlaceholderEntry] = {}
        self._auto_mask_enabled: bool = True
        self._load_globals()
        self._initialized = True

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_auto_mask_enabled(self, enabled: bool) -> None:
        """Enable / disable auto-detection of sensitive placeholders by name."""
        self._auto_mask_enabled = enabled
        for name, entry in self._entries.items():
            entry.auto_sensitive = self._compute_auto_sensitive(name)

    def _compute_auto_sensitive(self, name: str) -> bool:
        if not self._auto_mask_enabled:
            return False
        return bool(_SENSITIVE_PATTERN.search(name))

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan_text(self, *texts: str) -> set[str]:
        """Return set of all placeholder names found in the supplied texts."""
        names: set[str] = set()
        for text in texts:
            for m in _PLACEHOLDER_RE.finditer(text):
                names.add(m.group(1))
        return names

    def ensure_entries(self, names: set[str]) -> None:
        """Create entries for any newly discovered placeholder names."""
        for name in names:
            if name not in self._entries:
                self._entries[name] = PlaceholderEntry(
                    auto_sensitive=self._compute_auto_sensitive(name)
                )

    def remove_stale(self, active_names: set[str]) -> None:
        """Drop session-only entries whose names are no longer in either editor."""
        stale = [n for n, e in self._entries.items()
                 if n not in active_names and not e.is_global]
        for n in stale:
            del self._entries[n]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def set_value(self, name: str, value: str) -> None:
        self._ensure_entry(name)
        self._entries[name].value = value
        if self._entries[name].is_global:
            self._save_globals()

    def get_value(self, name: str) -> str:
        entry = self._entries.get(name)
        return entry.value if entry else ""

    def set_global(self, name: str, is_global: bool) -> None:
        self._ensure_entry(name)
        self._entries[name].is_global = is_global
        self._save_globals()     # re-save (adds or removes the entry)

    def set_sensitive(self, name: str, is_sensitive: bool) -> None:
        self._ensure_entry(name)
        self._entries[name].is_sensitive = is_sensitive

    def all_entries(self) -> Dict[str, PlaceholderEntry]:
        return dict(self._entries)

    def filled_names(self) -> set[str]:
        return {n for n, e in self._entries.items() if e.is_filled()}

    # ------------------------------------------------------------------
    # Text operations
    # ------------------------------------------------------------------

    def substitute_text(self, text: str) -> str:
        """Replace every {{NAME}} token with its stored value (if filled)."""
        def _replace(m: re.Match) -> str:
            val = self.get_value(m.group(1))
            return val if val.strip() else m.group(0)
        return _PLACEHOLDER_RE.sub(_replace, text)

    def mask_for_llm(self, text: str) -> str:
        """Reverse substitution: replace any literal filled values back to
        {{NAME}} before the text is sent to an LLM.

        Protects against accidental leakage when a user has typed a real value
        directly into the editor instead of using the Placeholder Panel.
        Only values longer than _MIN_MASK_LEN characters are considered to
        avoid false positives on short common strings.
        """
        result = text
        for name, entry in self._entries.items():
            if entry.is_filled() and len(entry.value) >= _MIN_MASK_LEN:
                result = result.replace(entry.value, f"{{{{{name}}}}}")
        return result

    # ------------------------------------------------------------------
    # Global persistence
    # ------------------------------------------------------------------

    def _save_globals(self) -> None:
        global_data = {
            name: {
                "value": e.value,
                "is_sensitive": e.is_sensitive,
            }
            for name, e in self._entries.items()
            if e.is_global
        }
        try:
            os.makedirs(os.path.dirname(_GLOBAL_STORE_PATH), exist_ok=True)
            with open(_GLOBAL_STORE_PATH, "w", encoding="utf-8") as f:
                json.dump(global_data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("PlaceholderManager: failed to save globals: %s", exc)

    def _load_globals(self) -> None:
        if not os.path.exists(_GLOBAL_STORE_PATH):
            return
        try:
            with open(_GLOBAL_STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, d in data.items():
                self._entries[name] = PlaceholderEntry(
                    value=d.get("value", ""),
                    is_global=True,
                    is_sensitive=d.get("is_sensitive", False),
                    auto_sensitive=self._compute_auto_sensitive(name),
                )
            logger.info("PlaceholderManager: loaded %d global entries", len(data))
        except Exception as exc:
            logger.error("PlaceholderManager: failed to load globals: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_entry(self, name: str) -> None:
        if name not in self._entries:
            self._entries[name] = PlaceholderEntry(
                auto_sensitive=self._compute_auto_sensitive(name)
            )
