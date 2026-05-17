from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from src.managers.settings_manager import SettingsManager
from src.managers.api_preset_manager import ensure_api_presets_manager
from src.managers.app_paths import db_path, settings_path
from src.core.events import EventBus, set_event_bus
from src.services.llm_service import LLMService
from src.services.orchestrator import Orchestrator
from src.services.db_service import init_db_service
from src.ui.main_window import MainWindow
from src.controllers.chat_controller import ChatController
from src.controllers.editor_controller import EditorController
from src.controllers.history_controller import HistoryController


class GuiController:
    def __init__(
        self,
        main_window: MainWindow,
        llm_service: LLMService,
        orchestrator: Orchestrator,
        api_presets_manager: object,
    ):
        self.main_window = main_window

        # Keep key services/managers alive for the whole app lifetime
        self.llm_service = llm_service
        self.orchestrator = orchestrator
        self.api_presets_manager = api_presets_manager

        self.chat_controller = ChatController(self, main_window.chat_widget)
        self.editor_controller = EditorController(self, main_window.code_editor)
        self.history_controller = HistoryController(self, main_window.history_panel)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FlowArchitect")

    from src.ui.theme_manager import ThemeManager
    ThemeManager.get().load_from_settings()

    # EventBus (глобальный как в Mita)
    event_bus = EventBus()
    set_event_bus(event_bus)

    settings_mgr = SettingsManager(str(settings_path()))

    # Database
    _db = init_db_service(str(db_path()))

    # Services
    llm_service = LLMService(settings=settings_mgr, event_bus=event_bus)
    _orchestrator = Orchestrator(event_bus=event_bus, llm_service=llm_service)
    api_preset_manager = ensure_api_presets_manager()

    # UI
    win = MainWindow()
    _gui_controller = GuiController(win, llm_service, _orchestrator, api_preset_manager)

    # Restore last session state into UI
    _orchestrator.restore_last_session()

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
