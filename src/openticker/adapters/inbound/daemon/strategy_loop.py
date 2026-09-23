"""The daemon's strategy loop (ADR 21 in docs/adr): every second, writes the
starts strategies' schedules ask for (ADR 22), carries out the start, stop,
kill and close-leg commands, fetches quotes for legs the feed has gone quiet
on, then judges every open run at the latest prices (ADR 23). Its first pass
notes on every run left open that it is watched again.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.quote_poller import QuotePoller
from openticker.core.calendar.models import MarketCalendar
from openticker.core.strategies.prices import PriceTimeouts
from openticker.events.bus import EventPublisher
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.strategies.runner import (
    RunnerContext,
    process_commands,
    recover_runs,
    start_scheduled,
    step_runs,
    watched_legs,
)

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
        timeouts: PriceTimeouts | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._timeouts = timeouts or PriceTimeouts()
        self._poller = QuotePoller(
            lambda broker, instruments: sandbox(broker).get_quotes(instruments),
            prices,
            self._timeouts,
        )
        self._recovered = False
        self._started_at: datetime | None = None
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
            timeouts=self._timeouts,
            watching_from=self._started_at or now,
        )
        if not self._recovered:
            if count := recover_runs(context, now):
                log.info("watching %d strategy run(s) left open by the last run", count)
            self._recovered = True
            self._started_at = now
        start_scheduled(context, now)
        process_commands(context, now)
        self._poller.poll(watched_legs(context, now), now)
        step_runs(context, now)
