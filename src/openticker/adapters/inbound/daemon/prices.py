"""LatestPrices: the newest price per instrument, streamed or fetched as a
quote, shared by the daemon's threads (ADR 13 and ADR 23 in docs/adr)."""

import threading
from collections.abc import Iterable
from datetime import datetime

from openticker.ports.models import Instrument, Tick


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
