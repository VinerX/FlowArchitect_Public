from __future__ import annotations

from typing import Any

from main_logger import logger
from src.core.events import Events
from src.controllers.base_controller import BaseController


def _get_db():
    try:
        from src.services.db_service import get_db_service
        return get_db_service()
    except Exception:
        return None


def _get_active_session_id() -> int | None:
    """Get the active session id from the Orchestrator via EventBus (best-effort)."""
    try:
        from src.core.events import get_event_bus
        bus = get_event_bus()
        # The orchestrator subscribes to USER_QUERY; we reach it via its attribute
        # stored on the bus. Since we don't have a direct reference, use db service
        # to get the last session.
        db = _get_db()
        if db:
            session = db.get_last_session()
            return session["id"] if session else None
    except Exception:
        pass
    return None


class ChatController(BaseController):
    def __init__(self, main_controller: Any, view: Any):
        super().__init__(main_controller, view)

        # UI -> controller
        if self.view is not None and hasattr(self.view, "send_message_signal"):
            self.view.send_message_signal.connect(self._on_user_send)
        if self.view is not None and hasattr(self.view, "delete_message_requested"):
            self.view.delete_message_requested.connect(self._on_delete_message)
        if self.view is not None and hasattr(self.view, "regenerate_requested"):
            self.view.regenerate_requested.connect(self._on_regenerate)

    def subscribe_to_events(self):
        # Orchestrator -> UI
        self.event_bus.subscribe(Events.Chat.NEW_MESSAGE, self._on_new_message, weak=False)
        self.event_bus.subscribe(Events.Chat.USER_MESSAGE_SAVED, self._on_user_message_saved, weak=False)
        self.event_bus.subscribe(Events.Etl.ERROR, self._on_etl_error, weak=False)
        self.event_bus.subscribe(Events.Session.LOADED, self._on_session_loaded, weak=False)
        self.event_bus.subscribe(Events.Etl.PIM_GENERATED, self._on_pim_generated, weak=False)
        self.event_bus.subscribe(Events.NiFi.IMPORT_RESULT, self._on_nifi_import_result, weak=False)

    def _on_user_send(self, text: str):
        text = (text or "").strip()
        if not text:
            return

        self._ui(lambda: self.view.append_message("user", text))
        self._ui(lambda: self.view.clear_input())
        self._ui(lambda: self.view.show_waiting("Генерация PIM-модели (YAML)"))

        # В событие для пайплайна
        self.event_bus.emit(Events.Etl.USER_QUERY, {"query": text})
        # Note: the user message is saved to DB by Orchestrator._on_user_query,
        # which has access to the session_id at that point.

    def _on_new_message(self, *args: Any, **kwargs: Any):
        payload = self._extract_payload(*args, **kwargs)
        text = (payload.get("text") or payload.get("message") or payload.get("content") or "").strip()
        role = (payload.get("role") or "assistant").strip()

        if not text:
            return

        self._ui(lambda: self.view.hide_waiting())
        self._ui(lambda: self.view.append_message(role, text))

        # Persist message to DB.
        # Prefer session_id from payload (set by orchestrator) — reliable and avoids
        # a DB round-trip.  Fall back to _get_active_session_id() for legacy callers.
        db = _get_db()
        if db:
            session_id = payload.get("session_id") or _get_active_session_id()
            if session_id:
                try:
                    db_id = db.save_message(session_id, role, text)
                    self._ui(lambda _id=db_id: self.view.update_last_message_db_id(_id))
                except Exception:
                    logger.debug("Failed to persist message to DB", exc_info=True)

    def _on_session_loaded(self, *args: Any, **kwargs: Any):
        """Reload chat view when a past session is restored."""
        payload = self._extract_payload(*args, **kwargs)
        messages = payload.get("messages", [])

        def _reload():
            if hasattr(self.view, "hide_waiting"):
                self.view.hide_waiting()
            if hasattr(self.view, "clear_messages"):
                self.view.clear_messages()
            for msg in messages:
                role = msg.get("role", "assistant")
                content = msg.get("content", "")
                if content:
                    self.view.append_message(role, content, db_id=msg.get("id"))

        self._ui(_reload)

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

    def _on_pim_generated(self, *args: Any, **kwargs: Any):
        self._ui(lambda: self.view.set_waiting_stage("Подготовка NiFi JSON"))
        self._ui(lambda: self.view.append_message("service", "PIM generated"))

    def _on_nifi_import_result(self, *args: Any, **kwargs: Any):
        from src.managers.settings_manager import SettingsManager

        payload = self._extract_payload(*args, **kwargs)
        ok = payload.get("ok", False)

        validation_errors: list[dict] = []
        error_lines: list[str] = []

        if ok:
            pg_id = payload.get("pg_id", "")
            validation_errors = payload.get("validation_errors") or []

            if not validation_errors:
                role = "service_ok"
                text = f"Flow successfully imported to NiFi.\nProcess-group ID: {pg_id}"
            else:
                role = "service_warn"
                lines = [f"Flow imported to NiFi (ID: {pg_id}), but validation errors were found:"]
                for item in validation_errors:
                    name = item.get("name") or item.get("type", "")
                    for err in item.get("errors", []):
                        line = f"  • [{name}] {err}"
                        lines.append(line)
                        error_lines.append(f"[{name}] {err}")
                lines.append("\nDescribe the fixes needed and I will update the YAML.")
                text = "\n".join(lines)
        else:
            role = "service_err"
            error = payload.get("error", "")
            text = f"NiFi import failed:\n{error}"

        _role = role  # capture for lambda
        self._ui(lambda: self.view.append_message(_role, text))

        if validation_errors and SettingsManager().get("LLM_NIFI_IMPORT_FIX_ENABLED", False):
            fix_prompt = (
                "NiFi validation errors were found after importing the flow:\n"
                + "\n".join(error_lines)
                + "\n\nPlease fix the YAML PIM to resolve these errors."
            )
            self._ui(lambda: self.view.show_waiting("Auto-fixing NiFi validation errors…"))
            self.event_bus.emit(Events.Etl.USER_QUERY, {"query": fix_prompt})

        db = _get_db()
        if db:
            session_id = _get_active_session_id()
            if session_id:
                try:
                    db.save_message(session_id, _role, text)
                except Exception:
                    logger.debug("Failed to persist NiFi import result to DB", exc_info=True)

    def _on_user_message_saved(self, *args: Any, **kwargs: Any) -> None:
        payload = self._extract_payload(*args, **kwargs)
        db_id = payload.get("db_id")
        if db_id is not None:
            self._ui(lambda _id=db_id: self.view.update_last_message_db_id(_id))

    def _on_delete_message(self, db_id: int) -> None:
        db = _get_db()
        if db:
            try:
                db.delete_message(db_id)
            except Exception:
                logger.debug("Failed to delete message from DB", exc_info=True)

    def _on_etl_error(self, *args: Any, **kwargs: Any):
        payload = self._extract_payload(*args, **kwargs)
        error_code = payload.get("error", "unknown_error")
        details = payload.get("details", "")

        error_msg = f"System Error: {error_code}"
        if details:
            error_msg += f"\nDetails: {details}"

        self._ui(lambda: self.view.hide_waiting())
        self._ui(lambda: self.view.append_message("system", error_msg))

    def _on_regenerate(self, text: str) -> None:
        """Re-send user query WITHOUT adding a new user bubble."""
        text = (text or "").strip()
        if not text:
            return
        self._ui(lambda: self.view.show_waiting("Генерация PIM-модели (YAML)"))
        self.event_bus.emit(Events.Etl.USER_QUERY, {"query": text})
