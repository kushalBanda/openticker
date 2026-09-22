"""A FakeBrokerPort whose prices a test can move."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time

from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Bar, Instrument, Quote
from tests.fixtures.fake_broker import FakeBrokerPort


class PricedBroker(FakeBrokerPort):
    def __init__(self, price: float = 100.0) -> None:
        self.price = price
        self.day_range: tuple[float, float] | None = None
        self.down = False
        self.closes: dict[tuple[str, date], float] = {}  # (symbol, day) -> daily close

    def get_quote(self, instrument: Instrument) -> Quote:
        if self.down:
            raise BrokerError("broker unreachable")
        low, high = self.day_range or (None, None)
        return Quote(instrument, self.price, datetime.now(UTC), day_low=low, day_high=high)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return [self.get_quote(instrument) for instrument in instruments]

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        """Daily candles for the days in `closes`, and nothing else."""
        if self.down:
            raise BrokerError("broker unreachable")
        return [
            Bar(
                instrument,
                interval,
                close,
                close,
                close,
                close,
                0,
                datetime.combine(day, time(0), EXCHANGE_TIMEZONE).astimezone(UTC),
            )
            for (symbol, day), close in sorted(self.closes.items())
            if symbol == instrument.symbol and start <= day <= end
        ]
