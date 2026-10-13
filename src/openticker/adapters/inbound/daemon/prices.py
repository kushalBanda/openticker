"""LatestPrices: the newest price per instrument, streamed or fetched as a
quote, shared by the daemon's threads (ADR 13 and ADR 23 in docs/adr)."""

import threading
from collections.abc import Iterable
from datetime import datetime

from openticker.core.calendar.models import SessionHours
from openticker.ports.models import Instrument, Tick
from openticker.use_cases.feed_status import QUIET_AFTER


class LatestPrices:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ticks: dict[tuple[str, str], Tick] = {}
        self._streamed_at: dict[tuple[str, str], datetime] = {}

    def update(self, ticks: Iterable[Tick]) -> None:
        """Prices from the live feed."""
        with self._lock:
            for tick in ticks:
                key = _key(tick.instrument)
                self._ticks[key] = tick
                self._streamed_at[key] = tick.received_at

    def update_polled(self, ticks: Iterable[Tick]) -> None:
        """Prices fetched as quotes while the feed is quiet. One never replaces
        a newer streamed price."""
        with self._lock:
            for tick in ticks:
                key = _key(tick.instrument)
                current = self._ticks.get(key)
                if current is None or current.received_at < tick.received_at:
                    self._ticks[key] = tick

    def get(self, instrument: Instrument) -> Tick | None:
        """The newest price, from either source."""
        with self._lock:
            return self._ticks.get(_key(instrument))

    def current(
        self, instrument: Instrument, now: datetime, session: SessionHours | None
    ) -> float | None:
        """Its price now, if the newest one known still is; None when only a
        quote would say. While the feed streams, an instrument that hasn't
        ticked hasn't traded elsewhere. Once `session` (the latest to open)
        has closed, a price from after the close is final, and so is one from
        during it if the feed was still streaming at the close."""
        with self._lock:
            tick = self._ticks.get(_key(instrument))
            last = max(self._streamed_at.values(), default=None)
        if tick is None:
            return None
        if last is not None and now - last < QUIET_AFTER:
            return tick.last_price
        if session is None or now < session.closes_at:
            return None
        if tick.received_at >= session.closes_at:
            return tick.last_price
        streamed_to_close = last is not None and last >= session.closes_at - QUIET_AFTER
        return (
            tick.last_price if streamed_to_close and tick.received_at >= session.opens_at else None
        )

    def streamed_at(self, instrument: Instrument) -> datetime | None:
        """When the live feed last priced it."""
        with self._lock:
            return self._streamed_at.get(_key(instrument))

    def last_streamed_at(self) -> datetime | None:
        """When the live feed last priced anything."""
        with self._lock:
            return max(self._streamed_at.values(), default=None)

    def snapshot(self) -> list[Tick]:
        with self._lock:
            return list(self._ticks.values())


def _key(instrument: Instrument) -> tuple[str, str]:
    return (instrument.exchange, instrument.symbol)
