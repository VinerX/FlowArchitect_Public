from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Optional

from pydantic import ValidationError

from src.domain.pim_model import Flow
from src.domain.llm_response_schema import OPENAI_JSON_FORMAT
from src.services.llm_service import LLMService
from src.services.plugin_manager import PluginManager
from src.services.prompt_service import PromptService

# Пытаемся импортировать Events из разных модулей
try:
    from src.core.events import Events  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.event_defines import Events  # type: ignore
    except Exception:  # pragma: no cover
        Events = None  # type: ignore

logger = logging.getLogger(__name__)

_SESSION_NAME_SYSTEM_PROMPT = (
    "You are a naming assistant. The user will describe a data pipeline task. "
    "Reply with ONLY a short session name (3-6 words, title case, no quotes, no punctuation at end). "
    "Example: 'Kafka To Postgres Filter Orders'"
)


class Orchestrator:
    MODE_DIRECT = 0
    MODE_ADAPTER = 1
    MODE_LLM = 2
    MODE_ADAPTER_LLM = 3  # Adapter → NiFi JSON → LLM semantic correction

    """
    Оркестратор MDA-пайплайна:
      mode=0: USER_QUERY -> LLM -> NiFi JSON -> UPDATE_CODE(kind=json)
      mode=1: USER_QUERY -> LLM -> YAML -> UPDATE_CODE(kind=yaml)
              REQUEST_CONVERSION -> YAML -> PIM -> NiFi JSON -> UPDATE_CODE(kind=json)
      mode=2: USER_QUERY -> LLM -> YAML -> UPDATE_CODE(kind=yaml)
              REQUEST_CONVERSION -> YAML -> LLM -> NiFi JSON -> UPDATE_CODE(kind=json)
    """

    def __init__(
        self,
        event_bus: Any,
        llm_service: LLMService,
        prompt_service: Optional[PromptService] = None,
        plugin_manager: Optional[PluginManager] = None,
    ):
        self.event_bus = event_bus
        self.llm_service = llm_service
        self.prompt_service = prompt_service or PromptService()
        self.plugin_manager = plugin_manager or PluginManager()

        self._last_yaml: Optional[str] = None
        self._last_pim: Optional[Flow] = None
        self._last_mode: int = self.MODE_ADAPTER
        self._active_session_id: Optional[int] = None

        # Events
        self._ev_user_query = self._resolve_event(("Etl", "USER_QUERY"), fallback="etl.user_query")
        self._ev_request_conversion = self._resolve_event(
            ("Etl", "REQUEST_CONVERSION"),
            fallback="etl.request_conversion",
        )
        self._ev_editor_update = self._resolve_event(("Editor", "UPDATE_CODE"), fallback="editor.update_code")
        self._ev_etl_error = self._resolve_event(("Etl", "ERROR"), fallback="etl.error")
        self._ev_session_created = self._resolve_event(("Session", "CREATED"), fallback="session.created")
        self._ev_session_name_updated = self._resolve_event(("Session", "NAME_UPDATED"), fallback="session.name_updated")
        self._ev_session_list_updated = self._resolve_event(("Session", "LIST_UPDATED"), fallback="session.list_updated")
        self._ev_pim_generated = self._resolve_event(("Etl", "PIM_GENERATED"), fallback="etl_pim_generated")
        self._ev_chat_new_message = self._resolve_event(("Chat", "NEW_MESSAGE"), fallback="chat.new_message")
        self._ev_tokens_reported = self._resolve_event(("Model", "TOKENS_REPORTED"), fallback="model_tokens_reported")
        self._last_llm_log_id: Optional[int] = None
        self._last_llm_preset_id: Any = None
        self._pending_token_usage: Optional[dict[str, int]] = None

        self._subscribe(self._ev_user_query, self._on_user_query)
        self._subscribe(self._ev_request_conversion, self._on_request_conversion)
        self._subscribe(self._ev_tokens_reported, self._on_tokens_reported)

    # -------------------------
    # Session helpers
    # -------------------------

    def _get_db(self):
        """Lazy import to avoid circular deps at module load time."""
        try:
            from src.services.db_service import get_db_service
            return get_db_service()
        except Exception:
            return None

    def _get_setting(self, key: str, default: Any = None) -> Any:
        """Read a setting from llm_service.settings (or llm_engine.settings as fallback)."""
        try:
            settings = getattr(self.llm_service, "settings", None)
            if settings is None:
                settings = self.llm_service.llm_engine.settings
            return settings.get(key, default)
        except Exception:
            return default

    def _ensure_session(self, mode: int) -> Optional[int]:
        """Return active session id, creating one in DB if needed."""
        db = self._get_db()
        if db is None:
            return None
        if self._active_session_id is None:
            self._active_session_id = db.create_session(mode=mode)
            self._publish(self._ev_session_created, {
                "session_id": self._active_session_id,
                "name": "New Session",
                "mode": mode,
            })
            self._publish(self._ev_session_list_updated, {})
        else:
            # Session was pre-created by HistoryController; update mode if it changed
            db.update_session_mode(self._active_session_id, mode)
        return self._active_session_id

    def _generate_session_name(self, query: str, preset_id: Any) -> None:
        """Call LLM with structured output to produce a short session name, then update DB."""
        session_id = self._active_session_id
        if session_id is None:
            return
        try:
            messages = [
                {"role": "system", "content": _SESSION_NAME_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ]
            name = self._llm_generate(messages=messages, preset_id=preset_id)
            if name:
                name = name.strip().strip('"\'').strip()[:80]
                db = self._get_db()
                if db:
                    db.update_session_name(session_id, name)
                self._publish(self._ev_session_name_updated, {
                    "session_id": session_id,
                    "name": name,
                })
                self._publish(self._ev_session_list_updated, {})
        except Exception:
            logger.debug("Session name generation failed (non-critical)", exc_info=True)

    def _log_llm_call(
        self,
        session_id: Optional[int],
        preset_id: Any,
        duration_ms: int,
        purpose: str,
    ) -> None:
        if session_id is None:
            return
        db = self._get_db()
        if db is None:
            return
        try:
            engine = getattr(self.llm_service, "llm_engine", None)
            resolver = getattr(engine, "preset_resolver", None)
            preset_settings = resolver.resolve(preset_id) if resolver else None
            provider = getattr(preset_settings, "provider_name", "") or ""
            model = getattr(preset_settings, "api_model", "") or ""
        except Exception:
            provider = ""
            model = ""
        try:
            self._last_llm_log_id = db.save_llm_log(
                session_id=session_id,
                provider=provider,
                model=model,
                duration_ms=duration_ms,
                purpose=purpose,
            )
            self._last_llm_preset_id = preset_id
            if self._pending_token_usage:
                prompt_tokens = self._pending_token_usage.get("prompt_tokens", 0)
                completion_tokens = self._pending_token_usage.get("completion_tokens", 0)
                cost = self._estimate_cost(preset_id, prompt_tokens, completion_tokens)
                db.update_llm_log_usage(self._last_llm_log_id, prompt_tokens, completion_tokens, cost)
                self._pending_token_usage = None
        except Exception:
            logger.debug("Failed to save LLM log", exc_info=True)

    def _on_tokens_reported(self, *args: Any, **kwargs: Any) -> None:
        payload = self._extract_payload(*args, **kwargs)
        prompt_tokens = int(payload.get("prompt_tokens") or 0)
        completion_tokens = int(payload.get("completion_tokens") or 0)
        self._pending_token_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        log_id = self._last_llm_log_id
        if not log_id:
            return
        cost = self._estimate_cost(self._last_llm_preset_id, prompt_tokens, completion_tokens)
        try:
            db = self._get_db()
            if db:
                db.update_llm_log_usage(log_id, prompt_tokens, completion_tokens, cost)
        except Exception:
            logger.debug("Failed to update LLM token usage", exc_info=True)

    def _estimate_cost(self, preset_id: Any, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
        try:
            if not isinstance(preset_id, int):
                return None
            data = self.event_bus.emit_and_wait(
                self._resolve_event(("ApiPresets", "GET_PRESET_FULL"), fallback="get_preset_full"),
                {"id": preset_id},
                timeout=1.0,
            )
            preset = data[0] if data else None
            if not isinstance(preset, dict):
                return None
            price_in = preset.get("price_input_per_1m")
            price_out = preset.get("price_output_per_1m")
            if price_in is None or price_out is None:
                return None
            cost = (prompt_tokens * float(price_in) + completion_tokens * float(price_out)) / 1_000_000
            return round(cost, 6)
        except Exception:
            return None

    def _timed_llm_generate(
        self,
        messages: list[dict[str, str]],
        preset_id: Any,
        purpose: str,
        response_format: Optional[dict] = None,
        request_timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Wrap _llm_generate with timing and DB logging."""
        t0 = time.monotonic()
        self._last_llm_log_id = None
        self._last_llm_preset_id = preset_id
        self._pending_token_usage = None
        result = self._llm_generate(
            messages=messages,
            preset_id=preset_id,
            response_format=response_format,
            request_timeout=request_timeout,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._log_llm_call(self._active_session_id, preset_id, duration_ms, purpose)
        return result

    def _stage_preset(self, stage: str, fallback: Any = None) -> Any:
        keys = {
            "pim": "LLM_STAGE_PIM_PRESET_ID",
            "psm": "LLM_STAGE_PSM_PRESET_ID",
            "error_corrector": "LLM_STAGE_ERROR_CORRECTOR_PRESET_ID",
            "nifi_corrector": "LLM_STAGE_NIFI_CORRECTOR_PRESET_ID",
        }
        value = self._get_setting(keys.get(stage, ""), None)
        return value if isinstance(value, int) and value > 0 else fallback

    def _stage_timeout(self, stage: str) -> float:
        keys = {
            "pim": "LLM_TIMEOUT_PIM_SEC",
            "psm": "LLM_TIMEOUT_PSM_SEC",
            "error_corrector": "LLM_TIMEOUT_ERROR_CORRECTOR_SEC",
            "nifi_corrector": "LLM_TIMEOUT_NIFI_CORRECTOR_SEC",
            "default": "LLM_TIMEOUT_DEFAULT_SEC",
        }
        stage_defaults = {
            "pim": 90,
            "psm": 120,
            "error_corrector": 240,
            "nifi_corrector": 300,
            "default": 45,
        }
        default = float(self._get_setting("LLM_TIMEOUT_DEFAULT_SEC", stage_defaults["default"]))
        try:
            return float(self._get_setting(keys.get(stage, "LLM_TIMEOUT_DEFAULT_SEC"), stage_defaults.get(stage, default)))
        except (TypeError, ValueError):
            return stage_defaults.get(stage, default)

    def _service_status(self, text: str, session_id: Optional[int], role: str = "service_info") -> None:
        self._publish(self._ev_chat_new_message, {
            "role": role,
            "text": text,
            "session_id": session_id,
        })

    # -------------------------
    # Session restore
    # -------------------------

    def restore_last_session(self) -> None:
        """Called on startup: restore editor state and active session from DB."""
        db = self._get_db()
        if db is None:
            return
        session = db.get_last_session()
        if not session:
            return
        session_id = session["id"]
        self._active_session_id = session_id
        self._last_mode = session.get("mode", self.MODE_ADAPTER)

        latest_pim = db.get_latest_pim(session_id)
        if latest_pim:
            self._last_yaml = latest_pim
            try:
                self._last_pim = self._parse_yaml_to_flow(latest_pim)
            except Exception:
                self._last_pim = None
            self._publish(self._ev_editor_update, {
                "kind": "yaml",
                "text": latest_pim,
                "code": latest_pim,
            })

        latest_nifi = db.get_latest_nifi(session_id)
        if latest_nifi:
            self._publish(self._ev_editor_update, {
                "kind": "json",
                "text": latest_nifi,
                "code": latest_nifi,
            })

        logger.info("Restored last session id=%s name=%r", session_id, session.get("name"))

    def restore_session(self, session_id: int) -> None:
        """Load an arbitrary past session into the editor and chat (called by HistoryController)."""
        db = self._get_db()
        if db is None:
            return
        data = db.get_full_session(session_id)
        if not data:
            return

        self._active_session_id = session_id
        self._last_mode = data.get("mode", self.MODE_ADAPTER)
        self._last_yaml = None
        self._last_pim = None

        if data.get("latest_pim"):
            self._last_yaml = data["latest_pim"]
            try:
                self._last_pim = self._parse_yaml_to_flow(data["latest_pim"])
            except Exception:
                pass
            self._publish(self._ev_editor_update, {
                "kind": "yaml",
                "text": data["latest_pim"],
                "code": data["latest_pim"],
            })

        if data.get("latest_nifi"):
            self._publish(self._ev_editor_update, {
                "kind": "json",
                "text": data["latest_nifi"],
                "code": data["latest_nifi"],
            })

        ev_session_loaded = self._resolve_event(("Session", "LOADED"), fallback="session.loaded")
        self._publish(ev_session_loaded, {
            "session_id": session_id,
            "name": data.get("name", ""),
            "messages": data.get("messages", []),
        })

    # -------------------------
    # Event bus helpers
    # -------------------------

    def _resolve_event(self, path: tuple[str, ...], fallback: str) -> Any:
        if Events is None:
            return fallback
        obj: Any = Events
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                return fallback
        return obj

    def _subscribe(self, event_name: Any, handler: Callable[..., Any]) -> None:
        if hasattr(self.event_bus, "subscribe"):
            self.event_bus.subscribe(event_name, handler, weak=False)
            return
        if hasattr(self.event_bus, "on"):
            self.event_bus.on(event_name, handler)
            return
        raise RuntimeError("EventBus does not support subscribe/on API")

    def _publish(self, event_name: Any, payload: Any) -> None:
        if hasattr(self.event_bus, "publish"):
            self.event_bus.publish(event_name, payload)
            return
        if hasattr(self.event_bus, "emit"):
            self.event_bus.emit(event_name, payload)
            return
        if hasattr(self.event_bus, "dispatch"):
            self.event_bus.dispatch(event_name, payload)
            return
        logger.warning("EventBus has no publish/emit/dispatch; cannot publish event=%r", event_name)

    def _extract_payload(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if "payload" in kwargs and isinstance(kwargs["payload"], dict):
            return kwargs["payload"]
        if "data" in kwargs and isinstance(kwargs["data"], dict):
            return kwargs["data"]

        if len(args) >= 2 and isinstance(args[1], dict):
            return args[1]

        if args:
            if hasattr(args[0], "data") and isinstance(args[0].data, dict):
                return args[0].data
            if isinstance(args[0], dict):
                return args[0]
            if isinstance(args[0], str):
                payload: dict[str, Any] = {"text": args[0]}
                if len(args) >= 2 and isinstance(args[1], (int, str)):
                    payload["mode"] = args[1]
                return payload

        return {}

    # -------------------------
    # Pipeline steps
    # -------------------------

    def _on_user_query(self, *args: Any, **kwargs: Any) -> Optional[str]:
        payload = self._extract_payload(*args, **kwargs)
        mode = self._get_mode(payload, default=self._last_mode)
        self._last_mode = mode

        query = (payload.get("query") or payload.get("text") or "").strip()
        if not query:
            self._publish(self._ev_etl_error, {"error": "empty_query"})
            return None

        preset_id = payload.get("preset_id")
        is_new_session = self._active_session_id is None
        session_id = self._ensure_session(mode)

        db = self._get_db()
        if db and session_id:
            user_msg_id = db.save_message(session_id, "user", query)
            self._publish(
                self._resolve_event(("Chat", "USER_MESSAGE_SAVED"), fallback="chat_user_message_saved"),
                {"db_id": user_msg_id, "session_id": session_id},
            )

        if mode == self.MODE_DIRECT:
            try:
                system_prompt = self._get_prompt_or_fallback(
                    "direct_psm.txt",
                    {"query": query},
                    "Convert the user's natural language ETL request directly into a valid Apache NiFi JSON flow. Return JSON only.",
                )
            except Exception as e:
                logger.exception("Failed to read/format direct PSM prompt")
                self._publish(self._ev_etl_error, {"error": "prompt_error", "details": str(e)})
                return None

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]

            try:
                json_result = self._timed_llm_generate(messages=messages, preset_id=preset_id, purpose="direct")
            except Exception as e:
                logger.exception("Direct PSM generation failed")
                self._publish(self._ev_etl_error, {"error": "llm_generation_failed", "details": str(e)})
                return None

            if not json_result:
                self._publish(self._ev_etl_error, {"error": "empty_llm_result"})
                return None

            try:
                nifi_dict = self._parse_json_response(json_result)
            except Exception as e:
                logger.exception("Direct JSON parse failed")
                self._publish(self._ev_etl_error, {"error": "json_parse_failed", "details": str(e)})
                return None

            json_text = json.dumps(nifi_dict, ensure_ascii=False, indent=2)
            self._last_yaml = None
            self._last_pim = None

            if db and session_id:
                db.save_nifi_snapshot(session_id, json_text)

            self._publish(self._ev_editor_update, {"kind": "yaml", "text": "", "code": ""})
            self._publish(self._ev_editor_update, {"kind": "json", "text": json_text, "code": json_text})

            if is_new_session:
                self._generate_session_name(query, preset_id)

            return json_text

        # Adapter / LLM-to-LLM modes

        # Feature 2: include current YAML state so the LLM can refine it
        yaml_context = ""
        if self._last_yaml:
            yaml_context = (
                "\nCURRENT PIM STATE (YAML):\n"
                "The user already has a configuration. MODIFY it according to the new request.\n"
                "Preserve all unchanged parts. Return the COMPLETE updated PIM in the pim field.\n\n"
                + self._last_yaml
            )

        try:
            system_prompt = self.prompt_service.get_prompt(
                "system_architect.txt",
                {"current_yaml_context": yaml_context},
            )
        except Exception as e:
            logger.exception("Failed to read/format prompt")
            self._publish(self._ev_etl_error, {"error": "prompt_error", "details": str(e)})
            return None

        # Feature 4: strict mode — never ask clarifying questions
        if self._get_setting("LLM_ALWAYS_GENERATE", False):
            system_prompt += (
                "\n\nIMPORTANT: Always use response_type=\"generation\". "
                "Never ask clarifying questions regardless of missing details — make reasonable assumptions."
            )

        # Feature 1: full conversation history instead of a single user message
        messages = self._build_messages_with_history(
            system_prompt=system_prompt,
            session_id=session_id,
            fallback_query=query,
        )

        # Features 3 + 4: structured generation with correction loop
        pim_preset_id = self._stage_preset("pim", preset_id)
        self._service_status("Генерирую PIM YAML. Если модель вернет невалидный JSON/PIM, запущу корректор.", session_id)
        pim, yaml_text, clarification = self._generate_pim_with_correction(
            messages=messages,
            preset_id=pim_preset_id,
            purpose="pim_generation",
            session_id=session_id,
        )

        # Feature 4: LLM asked a clarification question — already published to chat
        if clarification is not None:
            return None

        if pim is None:
            self._publish(self._ev_etl_error, {"error": "pim_generation_failed_after_retries"})
            return None

        self._last_yaml = yaml_text
        self._last_pim = pim

        if db and session_id:
            db.save_pim_snapshot(session_id, yaml_text)

        self._publish(self._ev_editor_update, {"kind": "yaml", "text": yaml_text, "code": yaml_text})
        self._publish(self._ev_pim_generated, {"yaml": yaml_text})

        if is_new_session:
            self._generate_session_name(query, preset_id)

        # Feature 5: proactive suggestions (non-blocking)
        if self._get_setting("LLM_SUGGESTIONS_ENABLED", False):
            self._generate_suggestions(yaml_text, preset_id, session_id)

        return yaml_text

    def _on_request_conversion(self, *args: Any, **kwargs: Any) -> Optional[dict]:
        payload = self._extract_payload(*args, **kwargs)
        mode = self._get_mode(payload, default=self._last_mode)
        self._last_mode = mode

        if mode == self.MODE_DIRECT:
            self._publish(self._ev_etl_error, {"error": "conversion_not_required_for_direct_mode"})
            return None

        yaml_text = (payload.get("yaml") or payload.get("text") or self._last_yaml or "").strip()
        if not yaml_text:
            self._publish(self._ev_etl_error, {"error": "no_yaml_to_convert"})
            return None

        self._last_yaml = yaml_text

        preset_id = payload.get("preset_id")
        session_id = self._ensure_session(mode)
        db = self._get_db()

        if mode == self.MODE_LLM:
            try:
                self._parse_yaml_to_flow(yaml_text)
            except Exception as e:
                logger.exception("YAML validation failed before LLM conversion")
                self._publish(self._ev_etl_error, {"error": "pim_parse_failed", "details": str(e)})
                return None

            # Mask any filled placeholder values before sending to LLM
            try:
                from src.managers.placeholder_manager import PlaceholderManager
                yaml_for_llm = PlaceholderManager().mask_for_llm(yaml_text)
                if yaml_for_llm != yaml_text:
                    logger.info(
                        "Orchestrator: masked %d filled placeholder value(s) before LLM call",
                        yaml_text.count("{{") - yaml_for_llm.count("{{"),
                    )
            except Exception:
                yaml_for_llm = yaml_text   # fail-open; never block the conversion

            try:
                system_prompt = self._get_prompt_or_fallback(
                    "psm_nifi.txt",
                    {"yaml": yaml_for_llm},
                    "Convert the provided YAML PIM specification into a valid Apache NiFi JSON flow. Return JSON only.",
                )
            except Exception as e:
                logger.exception("Failed to read/format PSM NiFi prompt")
                self._publish(self._ev_etl_error, {"error": "prompt_error", "details": str(e)})
                return None

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": yaml_for_llm},
            ]

            try:
                psm_preset_id = self._stage_preset("psm", preset_id)
                self._service_status("Конвертирую PIM YAML в NiFi JSON через LLM.", session_id)
                json_result = self._timed_llm_generate(
                    messages=messages,
                    preset_id=psm_preset_id,
                    purpose="psm_conversion",
                    request_timeout=self._stage_timeout("psm"),
                )
            except Exception as e:
                logger.exception("LLM conversion to NiFi failed")
                self._publish(self._ev_etl_error, {"error": "llm_generation_failed", "details": str(e)})
                return None

            if not json_result:
                self._publish(self._ev_etl_error, {"error": "empty_llm_result"})
                return None

            try:
                nifi_dict = self._parse_json_response(json_result)
            except Exception as e:
                logger.exception("LLM JSON parse failed")
                self._publish(self._ev_etl_error, {"error": "json_parse_failed", "details": str(e)})
                return None

            self._last_pim = None
            json_text = json.dumps(nifi_dict, ensure_ascii=False, indent=2)

            if db and session_id:
                db.save_nifi_snapshot(session_id, json_text)

            self._publish(self._ev_editor_update, {"kind": "json", "text": json_text, "code": json_text})
            return nifi_dict

        # MODE_ADAPTER_LLM: YAML → PIM → NiFiAdapter → NiFi JSON → LLM semantic correction
        if mode == self.MODE_ADAPTER_LLM:
            if self._last_pim is not None and yaml_text == self._last_yaml:
                pim = self._last_pim
            else:
                try:
                    pim = self._parse_yaml_to_flow(yaml_text)
                except Exception as e:
                    logger.exception("YAML -> PIM parse failed")
                    self._publish(self._ev_etl_error, {"error": "pim_parse_failed", "details": str(e)})
                    return None
                self._last_pim = pim
                self._last_yaml = yaml_text

            self._warn_manual_triggers(pim)

            try:
                adapter = self.plugin_manager.get_adapter(target="nifi")
                nifi_dict = adapter.convert(pim)
            except Exception as e:
                logger.exception("Conversion to NiFi failed")
                self._publish(self._ev_etl_error, {"error": "conversion_failed", "details": str(e)})
                return None

            adapter_json = json.dumps(nifi_dict, ensure_ascii=False, indent=2)

            corrected = self._correct_nifi_json(
                nifi_json=adapter_json,
                pim_yaml=yaml_text,
                preset_id=self._stage_preset("nifi_corrector", preset_id),
            )
            if corrected:
                final_json = corrected
            else:
                final_json = adapter_json
                self._publish(self._ev_chat_new_message, {
                    "role": "service_warn",
                    "text": "⚠ LLM-коррекция не удалась — показан адаптер-output без семантических правок.",
                    "session_id": session_id,
                })

            if db and session_id:
                db.save_nifi_snapshot(session_id, final_json)

            self._publish(self._ev_editor_update, {"kind": "json", "text": final_json, "code": final_json})
            return json.loads(final_json)

        # MODE_ADAPTER: YAML -> PIM -> NiFi JSON через адаптер
        if self._last_pim is not None and yaml_text == self._last_yaml:
            pim = self._last_pim
            logger.debug("Re-using cached PIM (YAML unchanged).")
        else:
            try:
                pim = self._parse_yaml_to_flow(yaml_text)
            except Exception as e:
                logger.exception("YAML -> PIM parse failed")
                self._publish(self._ev_etl_error, {"error": "pim_parse_failed", "details": str(e)})
                return None
            self._last_pim = pim
            self._last_yaml = yaml_text

        self._warn_manual_triggers(pim)

        try:
            adapter = self.plugin_manager.get_adapter(target="nifi")
            nifi_dict = adapter.convert(pim)
        except Exception as e:
            logger.exception("Conversion to NiFi failed")
            self._publish(self._ev_etl_error, {"error": "conversion_failed", "details": str(e)})
            return None

        json_text = json.dumps(nifi_dict, ensure_ascii=False, indent=2)

        if db and session_id:
            db.save_nifi_snapshot(session_id, json_text)

        self._publish(self._ev_editor_update, {"kind": "json", "text": json_text, "code": json_text})
        return nifi_dict

    # -------------------------
    # Internals
    # -------------------------

    def _correct_nifi_json(
        self,
        nifi_json: str,
        pim_yaml: str,
        preset_id: Any,
    ) -> Optional[str]:
        """
        Ask the LLM to fix only semantic issues in the adapter-generated NiFi JSON.
        Structural elements (UUIDs, bundle versions, connections) must not change.
        Returns corrected JSON string, or None if correction failed.
        """
        try:
            system_prompt = self._get_prompt_or_fallback(
                "nifi_corrector.txt",
                {"pim_yaml": pim_yaml, "nifi_json": nifi_json},
                (
                    "You are an Apache NiFi expert. Fix ONLY semantic errors in the NiFi JSON below.\n"
                    "Do NOT change UUIDs, structure, or bundle versions.\n"
                    "Return the corrected JSON enclosed in ```json ... ``` fences.\n\n"
                    f"PIM (context):\n{pim_yaml}\n\nNiFi JSON:\n{nifi_json}"
                ),
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Fix semantic errors and return the corrected NiFi JSON."},
            ]
            result = self._timed_llm_generate(
                messages=messages,
                preset_id=preset_id,
                purpose="nifi_correction",
                request_timeout=self._stage_timeout("nifi_corrector"),
            )
            if not result:
                return None
            corrected_dict = self._parse_json_response(result)
            return json.dumps(corrected_dict, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("NiFi JSON correction failed (non-critical); using adapter output", exc_info=True)
            return None

    def _warn_manual_triggers(self, pim: Flow) -> None:
        """Emit a visible warning if the PIM contains manual triggers."""
        manual_ids = [t.id for t in pim.triggers if t.type == "manual"]
        if not manual_ids:
            return
        logger.warning(
            "PIM contains manual trigger(s): %s — flow will not start automatically in NiFi.",
            manual_ids,
        )
        self._publish(
            self._ev_etl_error,
            {
                "error": "manual_trigger_warning",
                "details": (
                    f"Trigger(s) {manual_ids} have type 'manual'.\n"
                    "The flow will NOT start automatically in NiFi — "
                    "someone must press Run in the NiFi UI.\n"
                    "Change trigger type to 'schedule' or 'event' for production use."
                ),
            },
        )

    def _parse_json_to_flow(self, json_text: str) -> Flow:
        """Parse structured JSON output from LLM directly into a PIMFlow."""
        raw = self._extract_json(json_text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM output is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object/dict")
        try:
            return Flow.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"PIM validation error: {e}") from e

    def _pim_to_yaml(self, pim: Flow) -> str:
        """Serialise a PIMFlow back to a canonical YAML string for editor display."""
        try:
            import yaml
        except Exception as e:  # pragma: no cover
            raise RuntimeError("PyYAML is required (pip install pyyaml)") from e
        data = pim.model_dump(mode="json", exclude_none=True)
        return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # ------------------------------------------------------------------
    # YAML placeholder quoting
    # ------------------------------------------------------------------

    _BARE_PH_RE = re.compile(
        r"(:\s+)(\{\{[A-Za-z0-9_]+\}\})(\s*(?:#[^\n]*)?)$",
        re.MULTILINE,
    )

    @classmethod
    def _quote_bare_placeholders(cls, yaml_text: str) -> str:
        """Auto-quote bare {{PLACEHOLDER}} YAML values so the parser doesn't
        interpret the opening brace as a flow-mapping indicator.

        Transforms:  ``key: {{NAME}}``  →  ``key: "{{NAME}}"``
        Skips lines that already have quotes around the placeholder.
        """
        def _replace(m: re.Match) -> str:
            colon, ph, tail = m.group(1), m.group(2), m.group(3)
            return f'{colon}"{ph}"{tail}'

        # Only replace when the placeholder is NOT already inside quotes
        lines = []
        for line in yaml_text.splitlines(keepends=True):
            # Check if the placeholder is already quoted on this line
            if re.search(r'''['"]\{\{[A-Za-z0-9_]+\}\}['"]''', line):
                lines.append(line)
            else:
                lines.append(cls._BARE_PH_RE.sub(_replace, line))
        return "".join(lines)

    def _parse_yaml_to_flow(self, yaml_text: str) -> Flow:
        try:
            import yaml
        except Exception as e:
            raise RuntimeError("PyYAML is required to parse YAML (pip install pyyaml)") from e

        # Ensure bare {{PLACEHOLDER}} values are quoted before parsing
        yaml_text = self._quote_bare_placeholders(yaml_text)

        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping/object")

        try:
            return Flow.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"PIM validation error: {e}") from e

    def _llm_generate(
        self,
        messages: list[dict[str, str]],
        preset_id: Any = None,
        response_format: Optional[dict] = None,
        request_timeout: Optional[float] = None,
    ) -> Optional[str]:
        if hasattr(self.llm_service, "generate") and callable(getattr(self.llm_service, "generate")):
            return self.llm_service.generate(  # type: ignore[attr-defined]
                messages=messages,
                preset_id=preset_id,
                response_format=response_format,
                request_timeout=request_timeout,
            )
        return self.llm_service.llm_engine.generate(
            messages=messages,
            preset_id=preset_id,
            response_format=response_format,
            request_timeout=request_timeout,
        )

    # -------------------------
    # History / structured generation helpers
    # -------------------------

    def _build_messages_with_history(
        self,
        system_prompt: str,
        session_id: Optional[int],
        fallback_query: str = "",
    ) -> list[dict[str, str]]:
        """
        Build the messages list for an LLM call.
        System prompt is always first.  Then we try to load the full
        conversation history (user + assistant turns) from DB so the LLM
        understands prior context.  If history is unavailable we fall back to
        a single user message with ``fallback_query``.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if session_id is not None:
            db = self._get_db()
            if db is not None:
                try:
                    limit = int(self._get_setting("MODEL_MESSAGE_LIMIT", 40))
                    all_msgs = db.get_messages(session_id)
                    # Keep only real conversation turns; skip service/system roles
                    chat_msgs = [
                        {"role": m["role"], "content": m["content"]}
                        for m in all_msgs
                        if m.get("role") in ("user", "assistant")
                    ]
                    if len(chat_msgs) > limit:
                        chat_msgs = chat_msgs[-limit:]
                    messages.extend(chat_msgs)
                    return messages
                except Exception:
                    logger.debug("Failed to load history, falling back to simple messages", exc_info=True)

        # Fallback: no DB or exception — add the current query manually
        if fallback_query:
            messages.append({"role": "user", "content": fallback_query})
        return messages

    def _generate_pim_with_correction(
        self,
        messages: list[dict[str, str]],
        preset_id: Any,
        purpose: str,
        session_id: Optional[int],
    ) -> tuple[Optional[Flow], Optional[str], Optional[str]]:
        """
        Call the LLM and parse a structured ``{response_type, pim|message}``
        response.

        Returns ``(flow, yaml_text, None)`` on successful generation, or
        ``(None, None, clarification_text)`` when the LLM asks a question, or
        ``(None, None, None)`` on unrecoverable failure.
        """
        always_generate = bool(self._get_setting("LLM_ALWAYS_GENERATE", False))
        correction_enabled = bool(self._get_setting("LLM_ERROR_CORRECTION_ENABLED", True))
        max_retries = int(self._get_setting("LLM_ERROR_CORRECTION_MAX_RETRIES", 2))

        raw = self._timed_llm_generate(
            messages=messages,
            preset_id=preset_id,
            purpose=purpose,
            response_format=OPENAI_JSON_FORMAT,
            request_timeout=self._stage_timeout("pim"),
        )
        if not raw:
            return None, None, None

        # ------------------------------------------------------------------
        # Parse outer wrapper
        # ------------------------------------------------------------------
        try:
            wrapper = json.loads(self._extract_json(raw))
        except (json.JSONDecodeError, ValueError):
            # LLM returned something non-JSON — treat the whole response as a
            # raw PIM attempt so the correction loop can fix it
            wrapper = {}

        response_type = wrapper.get("response_type", "generation") if isinstance(wrapper, dict) else "generation"

        # ------------------------------------------------------------------
        # Clarification branch
        # ------------------------------------------------------------------
        if response_type == "clarification" and not always_generate:
            message = (wrapper.get("message") or "").strip() if isinstance(wrapper, dict) else ""
            if not message:
                message = raw.strip()
            # Publish with session_id so ChatController can persist it to DB
            self._publish(self._ev_chat_new_message, {
                "role": "assistant",
                "text": message,
                "session_id": session_id,
            })
            return None, None, message

        # ------------------------------------------------------------------
        # Generation branch — extract PIM data
        # ------------------------------------------------------------------
        # Support two shapes: {"response_type":"generation","pim":{...}} OR
        # the raw PIM dict (backward-compat with providers that ignore the wrapper)
        if isinstance(wrapper, dict) and "pim" in wrapper and isinstance(wrapper["pim"], dict):
            pim_data = wrapper["pim"]
        elif isinstance(wrapper, dict) and "flow" in wrapper:
            pim_data = wrapper
        else:
            pim_data = wrapper  # will likely fail validation; correction loop handles it

        broken_output = json.dumps(pim_data, ensure_ascii=False, indent=2) if isinstance(pim_data, dict) else raw
        validation_error: Optional[str] = None

        try:
            pim = Flow.model_validate(pim_data)
            return pim, self._pim_to_yaml(pim), None
        except (ValidationError, ValueError) as exc:
            validation_error = str(exc)
            logger.warning("PIM validation failed (attempt 0): %s", validation_error)

        if not correction_enabled:
            return None, None, None

        # ------------------------------------------------------------------
        # Error-correction retry loop
        # ------------------------------------------------------------------
        for attempt in range(1, max_retries + 1):
            notice = f"⚙ Auto-correction attempt {attempt}/{max_retries}…"
            self._publish(self._ev_chat_new_message, {
                "role": "service_warn",
                "text": notice,
                "session_id": session_id,
            })

            corrector_prompt = self._get_prompt_or_fallback(
                "error_corrector.txt",
                {"error_message": validation_error, "broken_output": broken_output},
                (
                    "You are a JSON debugger. The PIM below is invalid.\n"
                    f"ERROR:\n{validation_error}\n\n"
                    f"BROKEN OUTPUT:\n{broken_output}\n\n"
                    "Return a corrected JSON object with response_type=\"generation\" and pim field."
                ),
            )
            correction_messages = [
                {"role": "system", "content": corrector_prompt},
                {"role": "user", "content": "Fix the PIM and return the corrected JSON."},
            ]
            raw = self._timed_llm_generate(
                messages=correction_messages,
                preset_id=self._stage_preset("error_corrector", preset_id),
                purpose=f"error_correction_{attempt}",
                response_format=OPENAI_JSON_FORMAT,
                request_timeout=self._stage_timeout("error_corrector"),
            )
            if not raw:
                break
            try:
                wrapper = json.loads(self._extract_json(raw))
                if isinstance(wrapper, dict) and "pim" in wrapper and isinstance(wrapper["pim"], dict):
                    pim_data = wrapper["pim"]
                elif isinstance(wrapper, dict) and "flow" in wrapper:
                    pim_data = wrapper
                else:
                    pim_data = wrapper
                pim = Flow.model_validate(pim_data)
                return pim, self._pim_to_yaml(pim), None
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                validation_error = str(exc)
                broken_output = raw
                logger.warning("PIM correction attempt %d/%d failed: %s", attempt, max_retries, validation_error)

        return None, None, None

    def _generate_suggestions(
        self,
        yaml_text: str,
        preset_id: Any,
        session_id: Optional[int],
    ) -> None:
        """
        After a successful PIM generation, call the LLM to suggest improvements
        and publish the result as an assistant message (non-blocking; errors are
        silently logged).
        """
        try:
            prompt = self._get_prompt_or_fallback(
                "suggest_improvements.txt",
                {"yaml_content": yaml_text},
                (
                    "Review the PIM configuration below and suggest 2-3 concrete improvements. "
                    "Focus on error handling, performance, and data quality. "
                    "Be concise. Use bullet points. Do NOT regenerate the configuration.\n\n"
                    f"{yaml_text}"
                ),
            )
            suggestion_messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "What improvements would you suggest?"},
            ]
            suggestion = self._timed_llm_generate(
                messages=suggestion_messages,
                preset_id=preset_id,
                purpose="suggestions",
            )
            if suggestion:
                # Publish with session_id so ChatController persists it to DB
                self._publish(self._ev_chat_new_message, {
                    "role": "assistant",
                    "text": suggestion,
                    "session_id": session_id,
                })
        except Exception:
            logger.debug("Suggestions generation failed (non-critical)", exc_info=True)

    def _extract_yaml(self, text: str) -> str:
        t = text.strip()
        m = re.search(r"```(?:yaml|yml)?\s*(.*?)\s*```", t, flags=re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else t

    def _extract_json(self, text: str) -> str:
        t = text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", t, flags=re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else t

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        try:
            data = json.loads(self._extract_json(text))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse error: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object")
        return data

    def _get_prompt_or_fallback(
        self,
        prompt_name: str,
        variables: Optional[dict[str, Any]] = None,
        fallback: str = "",
    ) -> str:
        try:
            return self.prompt_service.get_prompt(prompt_name, variables or {})
        except Exception:
            if fallback:
                logger.warning("Failed to load prompt %s, using fallback", prompt_name, exc_info=True)
                return fallback
            raise

    def _get_mode(self, payload: dict[str, Any], default: Optional[int] = None) -> int:
        raw_mode = payload.get("mode")
        if raw_mode is None:
            raw_mode = payload.get("mode_index")
        if raw_mode is None:
            raw_mode = payload.get("conversion_mode")
        if raw_mode is None:
            raw_mode = payload.get("strategy")

        return self._normalize_mode(
            raw_mode,
            default=self.MODE_ADAPTER if default is None else default,
        )

    def _normalize_mode(self, raw_mode: Any, default: int = MODE_ADAPTER) -> int:
        _all_modes = (self.MODE_DIRECT, self.MODE_ADAPTER, self.MODE_LLM, self.MODE_ADAPTER_LLM)
        if isinstance(raw_mode, int) and raw_mode in _all_modes:
            return raw_mode

        if isinstance(raw_mode, str):
            value = raw_mode.strip().lower()

            if value.isdigit():
                idx = int(value)
                if idx in _all_modes:
                    return idx

            if value in {
                "direct",
                "direct nl -> psm",
                "direct nl -> psm (llm)",
            } or ("direct" in value and "psm" in value):
                return self.MODE_DIRECT

            if value in {
                "adapter_llm",
                "adapter+llm",
                "adapter + llm fix",
                "nl -> pim -> psm (adapter+llm)",
            } or ("adapter" in value and "llm" in value):
                return self.MODE_ADAPTER_LLM

            if value in {
                "adapter",
                "nl -> pim -> psm (adapter)",
            } or "adapter" in value:
                return self.MODE_ADAPTER

            if value in {
                "llm",
                "llm-to-llm",
                "nl -> pim -> psm (llm)",
            } or ("pim" in value and "llm" in value):
                return self.MODE_LLM

        if default in _all_modes:
            return default
        return self.MODE_ADAPTER
