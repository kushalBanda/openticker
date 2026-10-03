"""The daemon's P&L record (ADR 34 in docs/adr): a point each minute of the
session, and the day after its close.

`step()` does one pass and is what the tests drive; `run()` repeats it,
waking on each minute boundary.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time

from openticker.adapters.brokers.registry import BrokerConfigError
from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from openticker.storage.sqlite.pnl_repo import day_recorded
from openticker.use_cases.pnl_history import record_daily_pnl, record_intraday_point

log = logging.getLogger(__name__)

CLOSE_AFTER = time(15, 35)  # exchange-local: the day is recorded after this


class PnlLoop:
    def __init__(
        self,
        broker: Callable[[], BrokerPort],
        calendar: Callable[[], MarketCalendar],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """`broker`: the sandbox, pricing through the live broker."""
        self._broker = broker
        self._calendar = calendar
        self._clock = clock
        self._last_minute: datetime | None = None
        self._recorded: date | None = None

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.step()
            except Exception:  # a bug here must not end the daemon's record
                log.exception("P&L record failed")
            now = self._clock()
            stop.wait(60 - now.second - now.microsecond / 1e6 + 0.5)

    def step(self) -> None:
        now = self._clock()
        local = now.astimezone(EXCHANGE_TIMEZONE)
        hours = session_hours(local.date(), Exchange.NSE, self._calendar())
        if hours is None:
            return
        minute = local.replace(second=0, microsecond=0)
        if hours.opens_at <= local <= hours.closes_at and minute != self._last_minute:
            self._last_minute = minute
            try:
                record_intraday_point(self._broker(), now)
            except (BrokerError, BrokerConfigError) as exc:
                log.warning("P&L point at %s not recorded: %s", minute.time(), exc)
        after = datetime.combine(local.date(), CLOSE_AFTER, EXCHANGE_TIMEZONE)
        if local >= after and self._recorded != local.date():
            if not day_recorded(local.date()):
                try:
                    broker = self._broker()
                except BrokerConfigError:
                    return
                day = record_daily_pnl(local.date(), broker, now)
                log.info(
                    "P&L for %s recorded: %s after charges%s",
                    day.trading_date,
                    day.net_pnl,
                    " (estimated)" if day.estimated else "",
                )
            self._recorded = local.date()
