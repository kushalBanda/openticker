"""EventBus: in-process publish/subscribe with a bounded background queue
(ADR 10 in docs/adr).

A subscriber is either inline (runs in the publisher's thread before
`publish` returns, for work that must be durable before the caller moves on,
such as the audit log) or background (runs on a small thread pool, for slow
work such as HTTP notifications). When `max_pending` background handlers are
already queued, the next one runs inline instead: nothing is dropped and the
queue never grows without bound. A handler that raises is logged and never
affects the publisher or other handlers.
"""

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

E = TypeVar("E")

_Handler = Callable[[Any], None]


class EventPublisher(Protocol):
    def publish(self, event: object) -> None: ...


class EventBus:
    def __init__(self, max_pending: int = 1000, workers: int = 2) -> None:
        self._subscribers: dict[type, list[tuple[_Handler, bool]]] = defaultdict(list)
        self._slots = threading.BoundedSemaphore(max_pending)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="events")
        self._closed = False

    def subscribe(
        self, event_type: type[E], handler: Callable[[E], None], *, background: bool = True
    ) -> None:
        """Call `handler` for every published event that is an instance of
        `event_type` (subscribe to `object` for every event)."""
        self._subscribers[event_type].append((handler, background))

    def publish(self, event: object) -> None:
        for event_type in type(event).__mro__:
            for handler, background in self._subscribers.get(event_type, ()):
                if background and not self._closed and self._slots.acquire(blocking=False):
                    try:
                        future = self._executor.submit(_run, handler, event)
                    except RuntimeError:  # closed between the check and the submit
                        self._slots.release()
                        _run(handler, event)
                    else:
                        future.add_done_callback(self._release)
                else:
                    _run(handler, event)

    def close(self) -> None:
        """Wait for queued background handlers, then stop the pool. Events
        published afterwards run inline."""
        self._closed = True
        self._executor.shutdown(wait=True)

    def _release(self, _: "Future[None]") -> None:
        self._slots.release()


def _run(handler: _Handler, event: object) -> None:
    try:
        handler(event)
    except Exception:
        logger.exception("event handler %r failed for %r", handler, event)
