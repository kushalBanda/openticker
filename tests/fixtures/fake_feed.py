"""FakeFeed: a scripted MarketFeedPort. Tests queue tick batches or a
refused session; nothing touches a network."""

from collections.abc import Sequence

from openticker.ports.errors import BrokerSessionError
from openticker.ports.models import Instrument, Tick


class FakeFeed:
    def __init__(self) -> None:
        self.subscribed: dict[str, Instrument] = {}
        self.batches: list[list[Tick]] = []
        self.refused = False
        self.closed = False

    def subscribe(self, instruments: Sequence[Instrument]) -> None:
        self.subscribed.update({i.symbol: i for i in instruments})

    def unsubscribe(self, instruments: Sequence[Instrument]) -> None:
        for instrument in instruments:
            self.subscribed.pop(instrument.symbol, None)

    def ticks(self, timeout: float) -> list[Tick]:
        if self.refused:
            raise BrokerSessionError("session refused")
        return self.batches.pop(0) if self.batches else []

    def close(self) -> None:
        self.closed = True
