from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QTimer

from src.controllers.base_controller import BaseController
from src.core.events import Events

logger = logging.getLogger(__name__)


class HistoryController(BaseController):
    """
    Connects HistoryPanel (view) to DbService and the EventBus.

    Responsibilities:
    - Load session list on startup
    - Refresh list via QTimer (reliable, main-thread) every second
    - EventBus events still handled but only as extra triggers
    - Delegate session restore to Orchestrator via GuiController reference
    - Handle "New Session" button
    """

    _POLL_INTERVAL_MS = 1000

    def __init__(self, main_controller: Any, view: Any):
        self._last_session_count = -1  # track changes for stats refresh
        super().__init__(main_controller, view)

        if self.view is not None:
            self.view.session_selected.connect(self._on_session_selected)
            self.view.new_session_requested.connect(self._on_new_session_requested)
            self.view.session_rename_requested.connect(self._on_session_rename)
            self.view.session_delete_requested.connect(self._on_session_delete)

        # Initial load (main thread, direct call)
        self._do_refresh_sessions()
        self._do_refresh_stats()

        # Polling timer — runs entirely in the Qt main thread, no threading issues
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(self._POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()

    # ------------------------------------------------------------------
    # EventBus subscriptions (kept for name updates)
    # ------------------------------------------------------------------

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.Session.NAME_UPDATED, self._on_name_updated, weak=False)

    # ------------------------------------------------------------------
    # Timer poll (main thread, reliable)
    # ------------------------------------------------------------------

    def _on_poll(self) -> None:
        """Called every second from QTimer — always in the Qt main thread."""
        self._do_refresh_sessions()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_name_updated(self, *args: Any, **kwargs: Any) -> None:
        payload = self._extract_payload(*args, **kwargs)
        session_id = payload.get("session_id")
        name = payload.get("name", "")
        if session_id is not None and self.view is not None:
            self._ui(lambda: self.view.update_session_name(int(session_id), name))

    # ------------------------------------------------------------------
    # View signal handlers
    # ------------------------------------------------------------------

    def _on_session_selected(self, session_id: int) -> None:
        orchestrator = getattr(self.main_controller, "orchestrator", None)
        if orchestrator is None:
            logger.warning("HistoryController: no orchestrator on main_controller")
            return
        try:
            orchestrator.restore_session(session_id)
        except Exception:
            logger.exception("Failed to restore session id=%s", session_id)

    def _on_session_rename(self, session_id: int, new_name: str) -> None:
        db = self._get_db()
        if db is None:
            return
        try:
            db.update_session_name(session_id, new_name)
            self._do_refresh_sessions()
        except Exception:
            logger.exception("Failed to rename session id=%s", session_id)

    def _on_session_delete(self, session_id: int) -> None:
        db = self._get_db()
        if db is None:
            return
        try:
            db.delete_session(session_id)
            # If the deleted session is the currently active one, start fresh
            orchestrator = getattr(self.main_controller, "orchestrator", None)
            if orchestrator is not None:
                if getattr(orchestrator, "_active_session_id", None) == session_id:
                    self._on_new_session_requested()
                    return
            self._do_refresh_sessions()
            self._do_refresh_stats()
        except Exception:
            logger.exception("Failed to delete session id=%s", session_id)

    def _on_new_session_requested(self) -> None:
        """User clicked '+' → create a new DB session immediately and reset orchestrator."""
        orchestrator = getattr(self.main_controller, "orchestrator", None)
        db = self._get_db()

        # Create the session in DB right now so it appears in the list immediately
        new_session_id = None
        if db is not None:
            mode = getattr(orchestrator, "_last_mode", 1) if orchestrator else 1
            new_session_id = db.create_session(mode=mode, name="New Session")

        if orchestrator is not None:
            orchestrator._active_session_id = new_session_id
            orchestrator._last_yaml = None
            orchestrator._last_pim = None

        # Clear chat view (direct call — we're in the main thread here)
        chat_ctrl = getattr(self.main_controller, "chat_controller", None)
        if chat_ctrl is not None and chat_ctrl.view is not None:
            if hasattr(chat_ctrl.view, "clear_messages"):
                chat_ctrl.view.clear_messages()

        # Clear editor
        ev_update = Events.Editor.UPDATE_CODE
        self.event_bus.emit(ev_update, {"kind": "yaml", "text": "", "code": ""})
        self.event_bus.emit(ev_update, {"kind": "json", "text": "", "code": ""})

        # Immediate refresh (main thread — no signal magic needed)
        self._do_refresh_sessions()
        self._do_refresh_stats()

    # ------------------------------------------------------------------
    # Refresh helpers — always called in the main thread
    # ------------------------------------------------------------------

    def _do_refresh_sessions(self) -> None:
        """Query DB and update list widget. Must be called from the main thread."""
        db = self._get_db()
        if db is None or self.view is None:
            return
        try:
            sessions = db.list_sessions()
            count = len(sessions)
            self.view.load_sessions(sessions)
            if count != self._last_session_count:
                self._last_session_count = count
                self._do_refresh_stats()
        except Exception:
            logger.debug("Failed to refresh session list", exc_info=True)

    def _do_refresh_stats(self) -> None:
        """Query DB and update stats tab. Must be called from the main thread."""
        db = self._get_db()
        if db is None or self.view is None:
            return
        try:
            stats = db.get_stats()
            self.view.show_stats(stats)
        except Exception:
            logger.debug("Failed to refresh stats", exc_info=True)

    # Kept for compatibility — routes to main-thread helpers via _ui
    def _refresh_sessions(self) -> None:
        self._ui(self._do_refresh_sessions)

    def _refresh_stats(self) -> None:
        self._ui(self._do_refresh_stats)

    def _get_db(self):
        try:
            from src.services.db_service import get_db_service
            return get_db_service()
        except Exception:
            return None

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
            if isinstance(first, dict):
                return first
        return {}
