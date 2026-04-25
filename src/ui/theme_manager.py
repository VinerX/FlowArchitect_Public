"""ThemeManager — singleton that applies and persists the active theme.

Usage:
    from src.ui.theme_manager import ThemeManager

    tm = ThemeManager.get()
    tm.load_from_settings()          # call once at startup

    tm.apply("dark")                 # or "light"
    tm.toggle()                      # flip between dark/light

    # Subscribe to theme changes (widget re-render etc.)
    tm.register_on_change(my_callback)   # callback(theme_name: str)
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QApplication

from src.ui.theme import DARK, DARK_STYLESHEET, LIGHT, LIGHT_STYLESHEET


class ThemeManager:
    _instance: "ThemeManager | None" = None

    def __init__(self) -> None:
        self.current: str = "dark"
        self._palette: dict = DARK
        self._callbacks: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Theme application
    # ------------------------------------------------------------------

    def load_from_settings(self) -> None:
        """Read last saved theme from settings.json and apply it."""
        try:
            from src.managers.settings_manager import SettingsManager
            sm = SettingsManager()
            name = sm.get("theme", "dark")
        except Exception:
            name = "dark"
        self.apply(name, _save=False)

    def apply(self, name: str, *, _save: bool = True) -> None:
        """Apply theme by name ('dark' or 'light').

        Updates the QApplication stylesheet, persists to settings, and
        notifies all registered callbacks so widgets can re-render.
        """
        name = name if name in ("dark", "light") else "dark"
        self.current = name
        self._palette = DARK if name == "dark" else LIGHT

        app = QApplication.instance()
        if app is not None:
            ss = DARK_STYLESHEET if name == "dark" else LIGHT_STYLESHEET
            app.setStyleSheet(ss)

        if _save:
            try:
                from src.managers.settings_manager import SettingsManager
                SettingsManager().set("theme", name)
            except Exception:
                pass

        for cb in list(self._callbacks):
            try:
                cb(name)
            except Exception:
                pass

    def toggle(self) -> None:
        """Flip between dark and light."""
        self.apply("light" if self.current == "dark" else "dark")

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def register_on_change(self, callback: Callable[[str], None]) -> None:
        """Register a function to be called whenever the theme changes.

        The callback receives the new theme name as the only argument.
        Duplicate registrations are silently ignored.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_on_change(self, callback: Callable[[str], None]) -> None:
        """Remove a previously registered callback."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Read-only palette access
    # ------------------------------------------------------------------

    @property
    def palette(self) -> dict[str, str]:
        return self._palette


def get_theme_manager() -> ThemeManager:
    """Convenience accessor."""
    return ThemeManager.get()
