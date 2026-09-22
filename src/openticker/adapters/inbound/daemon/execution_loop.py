"""The daemon's sandbox execution loop (ADR 11 in docs/adr): every second,
fills or expires resting orders against LatestPrices; every 30 seconds,
closes intraday positions past their square-off and settles positions in
expired contracts.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderStatus
from openticker.events.bus import EventPublisher
from openticker.ports.broker_port import BrokerPort
from openticker.ports.sandbox_port import SandboxPort
from openticker.use_cases.execute_resting_orders import execute_resting_orders
from openticker.use_cases.settle_expired import settle_expired_positions
from openticker.use_cases.square_off import square_off_intraday

log = logging.getLogger(__name__)

SQUARE_OFF_CHECK = timedelta(seconds=30)
# After a failed square-off or a settlement still waiting for its price (no
# broker session, say), wait 5 minutes, then twice as long after each further
# failure, up to an hour: a failed square-off is notified, and a broker that
# stays down shouldn't mean a message every 5 minutes.
SQUARE_OFF_RETRY = timedelta(minutes=5)
SQUARE_OFF_RETRY_MAX = timedelta(hours=1)
CALENDAR_RELOAD = timedelta(minutes=10)


class Sandbox(BrokerPort, SandboxPort, Protocol):
    pass


class ExecutionLoop:
    def __init__(
        self,
        sandbox: Callable[[], Sandbox],
        prices: LatestPrices,
        events: EventPublisher,
        calendar: Callable[[], MarketCalendar],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sandbox = sandbox
        self._prices = prices
        self._events = events
        self._load_calendar = calendar
        self._clock = clock
        self._calendar: MarketCalendar | None = None
        self._calendar_loaded_at = datetime.min.replace(tzinfo=UTC)
        self._next_square_off = datetime.min.replace(tzinfo=UTC)
        self._square_off_retry = SQUARE_OFF_RETRY
        self._last_error: str | None = None

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.step()
                self._last_error = None
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if message != self._last_error:
                    log.exception("sandbox execution pass failed")
                    self._last_error = message
            stop.wait(1.0)

    def step(self) -> None:
        now = self._clock()
        if self._calendar is None or now - self._calendar_loaded_at >= CALENDAR_RELOAD:
            self._calendar = self._load_calendar()
            self._calendar_loaded_at = now
        sandbox = self._sandbox()
        execute_resting_orders(sandbox, self._prices.get, self._events, self._calendar, now)
        if now >= self._next_square_off:
            results = square_off_intraday(sandbox, sandbox, self._events, self._calendar, now)
            failed = [r.reason or "" for r in results if r.status is not OrderStatus.FILLED]
            for reason in failed:
                log.warning("square-off did not fill: %s", reason)
            settlement = settle_expired_positions(
                sandbox, sandbox, self._events, self._calendar, now
            )
            for waiting in settlement.waiting:
                log.warning("expiry settlement waiting: %s", waiting)
            failed += settlement.waiting
            if failed:
                self._next_square_off = now + self._square_off_retry
                self._square_off_retry = min(self._square_off_retry * 2, SQUARE_OFF_RETRY_MAX)
            else:
                self._next_square_off = now + SQUARE_OFF_CHECK
                self._square_off_retry = SQUARE_OFF_RETRY
