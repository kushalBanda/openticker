"""The daemon's strategy loop (ADR 21 in docs/adr): every second, carries out
the start, stop, kill and close-leg commands the MCP server and the REST API
wrote, then judges every open run at the latest live prices.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.calendar.models import MarketCalendar
from openticker.events.bus import EventPublisher
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.strategies.runner import RunnerContext, process_commands, step_runs

log = logging.getLogger(__name__)

CALENDAR_RELOAD = timedelta(minutes=10)


class StrategyLoop:
    def __init__(
        self,
        sandbox: Callable[[str], OrderSandbox],
        prices: LatestPrices,
        events: EventPublisher,
        calendar: Callable[[], MarketCalendar],
        capital_cap: float | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sandbox = sandbox
        self._prices = prices
        self._events = events
        self._load_calendar = calendar
        self._capital_cap = capital_cap
        self._clock = clock
        self._calendar: MarketCalendar | None = None
        self._calendar_loaded_at = datetime.min.replace(tzinfo=UTC)
        self._last_error: str | None = None

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.step()
                self._last_error = None
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if message != self._last_error:
                    log.exception("strategy runner pass failed")
                    self._last_error = message
            stop.wait(1.0)

    def step(self) -> None:
        now = self._clock()
        if self._calendar is None or now - self._calendar_loaded_at >= CALENDAR_RELOAD:
            self._calendar = self._load_calendar()
            self._calendar_loaded_at = now
        context = RunnerContext(
            sandbox=self._sandbox,
            latest=self._prices.get,
            events=self._events,
            calendar=self._calendar,
            capital_cap=self._capital_cap,
        )
        process_commands(context, now)
        step_runs(context, now)
