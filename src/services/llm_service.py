import logging
from typing import Any, Callable, Dict, Optional

from src.handlers.llm_engine import LLMEngine

# Пытаемся импортировать Events/EventBus из разных возможных модулей в src/core/
try:
    from src.core.events import Events  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.event_defines import Events  # type: ignore
    except Exception:  # pragma: no cover
        Events = None  # type: ignore

logger = logging.getLogger(__name__)


class LLMService:
    """
    Высокоуровневый сервис, который интегрирует LLMEngine в EventBus:
    - подписывается на событие запроса генерации
    - опционально стримит чанки в UI через события
    - публикует результат/ошибку
    """

    def __init__(self, settings, event_bus: Any, llm_engine: Optional[LLMEngine] = None):
        self.settings = settings
        self.event_bus = event_bus
        self.llm_engine = llm_engine or LLMEngine(settings=settings, event_bus=event_bus)

        self._ev_request = self._resolve_event(("Etl", "REQUEST_GENERATION"), fallback="etl.request_generation")
        self._ev_chunk = self._resolve_event(("Etl", "GENERATION_CHUNK"), fallback="etl.generation_chunk")
        self._ev_done = self._resolve_event(("Etl", "GENERATION_RESULT"), fallback="etl.generation_result")
        self._ev_failed = self._resolve_event(("Etl", "GENERATION_FAILED"), fallback="etl.generation_failed")

        self._subscribe(self._ev_request, self._on_request_generation)

    def _resolve_event(self, path: tuple[str, ...], fallback: str) -> Any:
        """
        Пытается достать Events.X.Y..., иначе возвращает fallback-строку.
        """
        if Events is None:
            return fallback
        obj: Any = Events
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                return fallback
        return obj

    def _subscribe(self, event_name: Any, handler: Callable[..., Any]) -> None:
        """
        Поддерживаем разные варианты EventBus API: subscribe/on.
        """
        if hasattr(self.event_bus, "subscribe"):
            self.event_bus.subscribe(event_name, handler,weak=False)
            return
        if hasattr(self.event_bus, "on"):
            self.event_bus.on(event_name, handler)
            return
        raise RuntimeError("EventBus does not support subscribe/on API")

    def _publish(self, event_name: Any, payload: Any) -> None:
        """
        Поддерживаем разные варианты EventBus API: publish/emit/dispatch.
        """
        if hasattr(self.event_bus, "publish"):
            self.event_bus.publish(event_name, payload)
            return
        if hasattr(self.event_bus, "emit"):
            self.event_bus.emit(event_name, payload)
            return
        if hasattr(self.event_bus, "dispatch"):
            self.event_bus.dispatch(event_name, payload)
            return

        # Если EventBus не поддерживает публикацию — просто логируем (чтобы не падать в стриминге)
        logger.warning("EventBus has no publish/emit/dispatch; cannot publish event=%r", event_name)

    def _on_request_generation(self, *args: Any, **kwargs: Any) -> Optional[str]:
        """
        Ожидаемый payload (dict):
          - messages: list[dict]
          - preset_id: int | None
          - request_id: str | int | None (опционально, для корреляции событий)
          - stream: bool (опционально; по умолчанию True)
          - stream_callback: callable (опционально; если UI сам передал callback)
          - reply_event: Any (опционально; куда отправить результат вместо default)
          - on_done: callable(result: str|None) (опционально)
        Возвращает результат синхронно, если EventBus использует прямой вызов.
        """
        payload = self._extract_payload(*args, **kwargs)
        messages = (payload or {}).get("messages") or []
        preset_id = (payload or {}).get("preset_id")
        request_id = (payload or {}).get("request_id")
        reply_event = (payload or {}).get("reply_event") or self._ev_done
        on_done = (payload or {}).get("on_done")
        request_timeout = (payload or {}).get("request_timeout")

        enable_streaming = bool(self.settings.get("ENABLE_STREAMING", False))
        stream_allowed = bool((payload or {}).get("stream", True))

        stream_cb: Optional[Callable[[str], None]] = None
        if enable_streaming and stream_allowed:
            # приоритет: явный stream_callback из payload
            if callable((payload or {}).get("stream_callback")):
                stream_cb = (payload or {})["stream_callback"]
            else:
                # иначе — шлем чанки в EventBus
                def _cb(chunk: str) -> None:
                    self._publish(
                        self._ev_chunk,
                        {
                            "request_id": request_id,
                            "chunk": chunk,
                        },
                    )

                stream_cb = _cb

        result = self.llm_engine.generate(
            messages=messages,
            preset_id=preset_id,
            stream_callback=stream_cb,
            request_timeout=request_timeout,
        )

        if result is None:
            self._publish(
                self._ev_failed,
                {
                    "request_id": request_id,
                    "preset_id": preset_id,
                    "error": "generation_failed",
                },
            )
        else:
            self._publish(
                reply_event,
                {
                    "request_id": request_id,
                    "preset_id": preset_id,
                    "text": result,
                },
            )

        if callable(on_done):
            try:
                on_done(result)
            except Exception:
                logger.exception("on_done callback failed")

        return result

    def generate(
        self,
        messages: list[dict[str, Any]],
        preset_id: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        response_format: Optional[dict[str, Any]] = None,
        request_timeout: Optional[float] = None,
    ) -> Optional[str]:
        return self.llm_engine.generate(
            messages=messages,
            preset_id=preset_id,
            stream_callback=stream_callback,
            response_format=response_format,
            request_timeout=request_timeout,
        )

    def _extract_payload(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Унификация входа под разные сигнатуры EventBus:
          - handler(payload)
          - handler(event, payload)
          - handler(..., payload=...)
          - handler(..., data=...)
        """
        if "payload" in kwargs and isinstance(kwargs["payload"], dict):
            return kwargs["payload"]
        if "data" in kwargs and isinstance(kwargs["data"], dict):
            return kwargs["data"]

        if len(args) == 1 and isinstance(args[0], dict):
            return args[0]
        if len(args) >= 2 and isinstance(args[1], dict):
            return args[1]

        return {}
