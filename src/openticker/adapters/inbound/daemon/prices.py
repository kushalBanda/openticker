"""LatestPrices: the newest streamed price per instrument, shared by the
daemon's threads (ADR 13 in docs/adr)."""

import threading
from collections.abc import Iterable

from openticker.ports.models import Instrument, Tick


class LatestPrices:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ticks: dict[tuple[str, str], Tick] = {}

    def update(self, ticks: Iterable[Tick]) -> None:
        with self._lock:
            for tick in ticks:
                self._ticks[(tick.instrument.exchange, tick.instrument.symbol)] = tick

    def get(self, instrument: Instrument) -> Tick | None:
        with self._lock:
            return self._ticks.get((instrument.exchange, instrument.symbol))

    def snapshot(self) -> list[Tick]:
        with self._lock:
            return list(self._ticks.values())
