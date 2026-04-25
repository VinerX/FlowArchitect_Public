import logging
from typing import Any, Callable, Dict, List, Optional

from src.managers.api_preset_resolver import ApiPresetResolver
from src.managers.llm_request_runner import LLMRequestRunner
from src.managers.model_config_loader import ModelConfigLoader

from src.handlers.llm_providers.base import LLMRequest
from src.handlers.llm_providers.param_mapper import build_unified_generation_params

logger = logging.getLogger(__name__)


class LLMEngine:
    """
    Низкоуровневый движок генерации: отвечает за построение LLMRequest и вызов LLMRequestRunner.
    Не знает про персонажей/состояние приложения/события UI, кроме минимально необходимого event_bus
    (нужен резолверу пресетов и раннеру).
    """

    def __init__(self, settings: Dict[str, Any], event_bus: Optional[Any] = None):
        self.settings = settings
        self.event_bus = event_bus

        # Preset resolver (CRITICAL)
        self.preset_resolver = ApiPresetResolver(settings=self.settings, event_bus=self.event_bus)
        try:
            preset_settings = self.preset_resolver.resolve()
            logger.info("Initializing LLMEngine with preset: %s", getattr(preset_settings, "preset_name", "<unknown>"))
        except Exception:
            logger.info("Initializing LLMEngine (preset resolution failed on startup; will resolve on request).")

        # Runtime config (CRITICAL)
        self.cfg_loader = ModelConfigLoader(self.settings)
        self.cfg = self.cfg_loader.load()
        if event_bus:
            event_bus.subscribe("setting_changed", self._on_setting_changed, weak=False)

        # Retry runner (CRITICAL)
        self.request_runner = LLMRequestRunner(
            settings=self.settings,
            preset_resolver=self.preset_resolver,
            event_bus=self.event_bus,
        )

    def _on_setting_changed(self, event) -> None:
        self.cfg = self.cfg_loader.load()

    def generate(
        self,
        messages: List[Dict[str, Any]],
        preset_id: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        request_timeout: Optional[float] = None,
    ) -> Optional[str]:
        """
        :param messages: список сообщений в unified-формате (role/content)
        :param preset_id: ID пресета провайдера (optional)
        :param stream_callback: callback для стриминга (optional)
        :param response_format: {"type": "json_object"} для принудительного JSON-вывода (optional)
        :return: чистый текст ответа или None при ошибке
        """
        if messages is None:
            messages = []

        try:
            return self._generate_chat_response(
                combined_messages=messages,
                preset_id=preset_id,
                stream_callback=stream_callback,
                response_format=response_format,
                request_timeout=request_timeout,
            )
        except Exception as e:
            logger.error("LLMEngine.generate failed unexpectedly: %s", e, exc_info=True)
            return None

    def _generate_chat_response(
        self,
        combined_messages: List[Dict[str, Any]],
        preset_id: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        request_timeout: Optional[float] = None,
    ) -> Optional[str]:
        max_attempts = self.cfg.max_request_attempts
        retry_delay = self.cfg.request_delay
        if request_timeout is None:
            request_timeout = float(self.settings.get("LLM_TIMEOUT_DEFAULT_SEC", 45))

        self._log_generation_start(preset_id)

        tools_on = bool(self.settings.get("TOOLS_ON", True))
        tools_mode = str(self.settings.get("TOOLS_MODE", "native") or "native").lower().strip()

        # legacy полностью удалён; если кто-то оставил в конфиге, просто отключаем/нормализуем
        if tools_mode == "off":
            tools_on = False
        elif tools_mode == "legacy":
            logger.warning("TOOLS_MODE=legacy is not supported anymore. Falling back to native tools.")
            tools_mode = "native"

        def build_request(preset_settings: Any, effective_model: str) -> LLMRequest:
            cfg = self.cfg_loader.effective_for_preset(self.cfg, preset_settings, effective_model)

            params = build_unified_generation_params(
                settings=self.settings,
                temperature=cfg.temperature,
                max_response_tokens=cfg.max_response_tokens,
                presence_penalty=cfg.presence_penalty,
                frequency_penalty=cfg.frequency_penalty,
                log_probability=cfg.log_probability,
                top_k=cfg.top_k,
                top_p=cfg.top_p,
                thinking_budget=cfg.thinking_budget,
            )

            tools_dialect = "gemini" if preset_settings.dialect_id == "gemini_generate_content" else "openai"

            req = LLMRequest(
                model=effective_model,
                messages=combined_messages,
                api_key=preset_settings.api_key,
                api_url=preset_settings.api_url,
                protocol_id=preset_settings.protocol_id,
                dialect_id=preset_settings.dialect_id,
                provider_name=preset_settings.provider_name,
                headers=dict(preset_settings.headers or {}),
                transforms=list(preset_settings.transforms or []),
                capabilities=dict(preset_settings.capabilities or {}),
                stream=bool(self.settings.get("ENABLE_STREAMING", False)) and stream_callback is not None,
                stream_cb=stream_callback,
                tools_on=tools_on,
                tools_mode=tools_mode,
                tools_payload=None,
                tools_dialect=tools_dialect,
                extra=params,
                settings=self.settings,
                response_format=response_format,
            )

            return req

        try:
            response_text = self.request_runner.run(
                messages=combined_messages,
                preset_id=preset_id,
                stream_callback=stream_callback,
                build_request=build_request,
                max_attempts=max_attempts,
                retry_delay=retry_delay,
                request_timeout=request_timeout,
            )
        except Exception as e:
            logger.error("LLMRequestRunner failed: %s", e, exc_info=True)
            return None

        if not response_text:
            return None

        cleaned = self._clean_response(response_text)
        if not cleaned:
            logger.warning("Response became empty after cleaning.")
            return None

        return cleaned

    def _log_generation_start(self, preset_id: Optional[int] = None) -> None:
        logger.info("Preparing to generate LLM response.")
        preset_settings = self.preset_resolver.resolve(preset_id)

        logger.info("Using preset: %s", getattr(preset_settings, "preset_name", "<unknown>"))
        logger.info(
            "Protocol: %s | Dialect: %s | Provider: %s",
            getattr(preset_settings, "protocol_id", None),
            getattr(preset_settings, "dialect_id", None),
            getattr(preset_settings, "provider_name", None),
        )
        logger.info("Capabilities: %s", getattr(preset_settings, "capabilities", None))
        logger.info("Max Response Tokens: %s, Temperature: %s", self.cfg.max_response_tokens, self.cfg.temperature)
        logger.info(
            "Presence Penalty: %s (Used: %s)",
            self.cfg.presence_penalty,
            bool(self.settings.get("USE_MODEL_PRESENCE_PENALTY")),
        )
        logger.info(
            "API URL: %s, API Model: %s",
            getattr(preset_settings, "api_url", None),
            getattr(preset_settings, "api_model", None),
        )

    def _clean_response(self, response_text: str) -> str:
        if not isinstance(response_text, str):
            logger.warning("Clean response expected string, got %s. Returning as is.", type(response_text))
            return response_text  # type: ignore[return-value]

        cleaned = response_text

        if cleaned.startswith("```json\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```json\n") : -len("\n```")]
        elif cleaned.startswith("```\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```\n") : -len("\n```")]
        elif cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3]

        return cleaned.strip()
