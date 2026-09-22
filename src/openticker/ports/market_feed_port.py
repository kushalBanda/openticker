"""MarketFeedPort: streaming prices from a broker (ADR 13 in docs/adr)."""

from collections.abc import Sequence
from typing import Protocol

from openticker.ports.models import Instrument, Tick


class MarketFeedPort(Protocol):
    def subscribe(self, instruments: Sequence[Instrument]) -> None: ...

    def unsubscribe(self, instruments: Sequence[Instrument]) -> None: ...

    def ticks(self, timeout: float) -> list[Tick]:
        """Blocks up to `timeout` seconds and returns what arrived; [] is
        normal. Raises `BrokerSessionError` once the broker has refused the
        session: the feed has stopped and needs a fresh login."""
        ...

    def close(self) -> None: ...
