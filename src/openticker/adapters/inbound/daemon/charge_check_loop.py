"""The daemon's daily charge-rate check (ADR 28 in docs/adr): once each day it
runs, it prices sample orders through the broker's contract note and
compares them with the rates the sandbox charges. Differences are published
as an event, which notifies. A check that can't run (the broker not
connected, instruments not synced) is tried again an hour later.

`step()` does one pass and is what the tests drive; `run()` repeats it.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from openticker.adapters.brokers.registry import BrokerConfigError
from openticker.core.orders.charges import ChargeBookError
from openticker.events.bus import EventPublisher
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.use_cases.check_charge_rates import NoChargeSamplesError, check_charge_rates

log = logging.getLogger(__name__)

RETRY = timedelta(hours=1)


class ChargeCheckLoop:
    def __init__(
        self,
        broker: str,
        adapter: Callable[[], BrokerPort],
        events: EventPublisher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._broker = broker
        self._adapter = adapter
        self._events = events
        self._clock = clock
        self._checked_on: date | None = None

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.step()
            except Exception:  # a bug here must not end the daemon's daily check
                log.exception("charge-rate check against %s failed", self._broker)
            stop.wait(RETRY.total_seconds())

    def step(self) -> None:
        now = self._clock()
        today = now.astimezone(EXCHANGE_TIMEZONE).date()
        if self._checked_on == today:
            return
        try:
            result = check_charge_rates(self._broker, self._adapter(), self._events, now, "daemon")
        except (BrokerError, BrokerConfigError, NoChargeSamplesError, ChargeBookError) as exc:
            log.warning("charge-rate check against %s not run: %s", self._broker, exc)
            return
        self._checked_on = today
        log.info(
            "charge rates checked against %s: %d of %d samples differ",
            self._broker,
            len(result.differing),
            len(result.samples),
        )
