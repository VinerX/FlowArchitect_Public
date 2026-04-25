import threading
from typing import Dict, List, Callable, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import weakref
from dataclasses import dataclass
from queue import Queue, Empty
import time
from main_logger import logger

# Re-export Events constants from the single source of truth.
# (Some modules may still import Events from core.events.)
from core.event_defines import Events

@dataclass
class Event:
    """Базовый класс для всех событий"""
    name: str
    data: Any = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class EventBus:
    """
    Потокобезопасная система событий с поддержкой слабых ссылок
    для предотвращения утечек памяти
    """

    def __init__(self, max_workers: int = 5):
        self._subscribers: Dict[str, List[weakref.ref]] = {}
        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        wait_workers = max(8, max_workers * 2)
        self._wait_executor = ThreadPoolExecutor(max_workers=wait_workers)

        self._event_queue = Queue()
        self._running = True
        self._processor_thread = threading.Thread(target=self._process_events, daemon=True)
        self._processor_thread.start()

    def subscribe(self, event_name: str, callback: Callable, weak: bool = True) -> None:
        """
        Подписаться на событие

        Args:
            event_name: Имя события
            callback: Функция обратного вызова
            weak: Использовать слабую ссылку (рекомендуется True)
        """
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []

            if weak:
                # Используем слабую ссылку для предотвращения циклических ссылок
                weak_ref = weakref.ref(callback, self._create_cleanup_callback(event_name))
                self._subscribers[event_name].append(weak_ref)
            else:
                # Для статических функций можно использовать сильные ссылки
                self._subscribers[event_name].append(callback)

            logger.debug(f"Подписка на событие '{event_name}' добавлена")

    def unsubscribe(self, event_name: str, callback: Callable) -> None:
        """Отписаться от события"""
        with self._lock:
            if event_name not in self._subscribers:
                return

            # Удаляем callback из списка подписчиков
            self._subscribers[event_name] = [
                ref for ref in self._subscribers[event_name]
                if not self._is_same_callback(ref, callback)
            ]

            # Удаляем пустые списки
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]

    def emit(self, event_name: str, data: Any = None, sync: bool = False) -> None:
        """
        Отправить событие

        Args:
            event_name: Имя события
            data: Данные события
            sync: Выполнить синхронно (блокирующий вызов)
        """
        event = Event(name=event_name, data=data)

        # Добавить отладку
        with self._lock:
            subscribers_count = len(self._get_active_subscribers(event_name))
            if subscribers_count > 0:
                logger.debug(f"Emitting event '{event_name}' to {subscribers_count} subscribers")
            else:
                logger.warning(f"No subscribers for event '{event_name}'")

        if sync:
            self._emit_sync(event)
        else:
            self._event_queue.put(event)

    def emit_and_wait(self, event_name: str, data: Any = None, timeout: float = 5.0) -> List[Any]:
        """
        Отправить событие и дождаться результатов от всех подписчиков
        """
        start_time = time.perf_counter()  # <--- СТАРТ ТАЙМЕРА
        is_main_thread = (threading.current_thread() is threading.main_thread())

        results: List[Any] = []
        result_queue: Queue = Queue()

        def result_wrapper(callback):
            def wrapper(*args, **kwargs):
                try:
                    result = callback(*args, **kwargs)
                    result_queue.put(result)
                except Exception as e:
                    logger.error("Произошла ошибка в событии, коллектим:")

                    callback_name = getattr(callback, "__qualname__", getattr(callback, "__name__", "unknown"))

                    event_name_for_log = "неизвестного события"

                    if args and isinstance(args[0], Event):
                        event_name_for_log = f"события '{args[0].name}'"

                    logger.error(
                        f"Ошибка в обработчике '{callback_name}' для {event_name_for_log}: {e}",
                        exc_info=True
                    )
                    result_queue.put(None)

            return wrapper

        with self._lock:
            subscribers = self._get_active_subscribers(event_name)

        if not subscribers:
            return results

        # Запуск задач
        for subscriber in subscribers:
            wrapped = result_wrapper(subscriber)
            self._wait_executor.submit(wrapped, Event(name=event_name, data=data))

        # Сбор результатов
        collected = 0
        target = len(subscribers)
        wait_start = time.time()

        while collected < target and (time.time() - wait_start) < float(timeout):
            try:
                result = result_queue.get(timeout=0.05)  # Чуть уменьшил шаг для отзывчивости
                if result is not None:
                    results.append(result)
                collected += 1
            except Empty:
                continue

        # --- ФИНАЛИЗАЦИЯ И ЛОГИРОВАНИЕ ВРЕМЕНИ ---
        duration = time.perf_counter() - start_time

        # Логируем, только если это заняло ощутимое время (например, > 100мс)
        if duration > 0.03:
            msg = f"⏱️ SLOW EVENT: '{event_name}' took {duration:.4f}s"

            if is_main_thread:
                # Если это MainThread - это 100% фриз интерфейса
                logger.warning(f"[GUI FREEZE] {msg} (Called from MainThread!)")
            else:
                # Если фоновый поток - просто инфо о медленной операции
                logger.info(f"[BG SLOW] {msg}")
        # -----------------------------------------

        return results

    def shutdown(self) -> None:
        """Остановить систему событий"""
        self._running = False
        self._event_queue.put(None)  # Сигнал для остановки
        self._processor_thread.join(timeout=5)

        try:
            self._executor.shutdown(wait=True)
        finally:
            self._wait_executor.shutdown(wait=True)

    def _process_events(self) -> None:
        """Обработчик очереди событий (работает в отдельном потоке)"""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.1)
                if event is None:  # Сигнал остановки
                    break

                self._emit_async(event)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Ошибка при обработке события: {e}", exc_info=True)

    def _emit_sync(self, event: Event) -> None:
        """Синхронная отправка события"""
        with self._lock:
            subscribers = self._get_active_subscribers(event.name)

        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception as e:
                logger.error(f"Ошибка при обработке события '{event.name}': {e}", exc_info=True)

    def _emit_async(self, event: Event) -> None:
        """Асинхронная отправка события"""
        with self._lock:
            subscribers = self._get_active_subscribers(event.name)

        for subscriber in subscribers:
            self._executor.submit(self._safe_call, subscriber, event)

    def _safe_call(self, callback: Callable, event: Event) -> None:
        """Безопасный вызов обработчика"""
        try:
            callback(event)
        except Exception as e:
            logger.error(f"Ошибка при обработке события '{event.name}': {e}", exc_info=True)

    def _get_active_subscribers(self, event_name: str) -> List[Callable]:
        """Получить список активных подписчиков"""
        if event_name not in self._subscribers:
            return []

        active_subscribers = []
        dead_refs = []

        for ref in self._subscribers[event_name]:
            if isinstance(ref, weakref.ref):
                callback = ref()
                if callback is not None:
                    active_subscribers.append(callback)
                else:
                    dead_refs.append(ref)
            else:
                # Сильная ссылка
                active_subscribers.append(ref)

        # Очистка мертвых ссылок
        if dead_refs:
            for dead_ref in dead_refs:
                self._subscribers[event_name].remove(dead_ref)

        return active_subscribers

    def _create_cleanup_callback(self, event_name: str):
        """Создать callback для очистки мертвых ссылок"""

        def cleanup(weak_ref):
            with self._lock:
                if event_name in self._subscribers:
                    try:
                        self._subscribers[event_name].remove(weak_ref)
                        if not self._subscribers[event_name]:
                            del self._subscribers[event_name]
                    except ValueError:
                        pass

        return cleanup

    def _is_same_callback(self, ref: Any, callback: Callable) -> bool:
        """Проверить, указывает ли ссылка на тот же callback"""
        if isinstance(ref, weakref.ref):
            return ref() is callback
        else:
            return ref is callback


# Глобальный экземпляр для удобства использования
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Получить глобальный экземпляр EventBus"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
def set_event_bus(bus: EventBus) -> None:
    global _global_event_bus
    _global_event_bus = bus

def shutdown_event_bus() -> None:
    """Остановить глобальный EventBus"""
    global _global_event_bus
    if _global_event_bus is not None:
        _global_event_bus.shutdown()
        _global_event_bus = None


# Удобные алиасы для быстрого доступа
def subscribe(event_name: str, callback: Callable, weak: bool = True) -> None:
    """Подписаться на событие через глобальный EventBus"""
    get_event_bus().subscribe(event_name, callback, weak)


def unsubscribe(event_name: str, callback: Callable) -> None:
    """Отписаться от события через глобальный EventBus"""
    get_event_bus().unsubscribe(event_name, callback)


def emit(event_name: str, data: Any = None, sync: bool = False) -> None:
    """Отправить событие через глобальный EventBus"""
    get_event_bus().emit(event_name, data, sync)


def emit_and_wait(event_name: str, data: Any = None, timeout: float = 5.0) -> List[Any]:
    """Отправить событие и дождаться результатов через глобальный EventBus"""
    return get_event_bus().emit_and_wait(event_name, data, timeout)
