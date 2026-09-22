"""A FakeBrokerPort whose prices a test can move."""

from collections.abc import Sequence
from datetime import UTC, datetime

from openticker.ports.errors import BrokerError
from openticker.ports.models import Instrument, Quote
from tests.fixtures.fake_broker import FakeBrokerPort


class PricedBroker(FakeBrokerPort):
    def __init__(self, price: float = 100.0) -> None:
        self.price = price
        self.day_range: tuple[float, float] | None = None
        self.down = False

    def get_quote(self, instrument: Instrument) -> Quote:
        if self.down:
            raise BrokerError("broker unreachable")
        low, high = self.day_range or (None, None)
        return Quote(instrument, self.price, datetime.now(UTC), day_low=low, day_high=high)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return [self.get_quote(instrument) for instrument in instruments]
