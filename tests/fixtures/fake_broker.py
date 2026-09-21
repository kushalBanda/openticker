"""FakeBrokerPort — a BrokerPort for tests. No network calls; fixed values."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus
from openticker.ports.models import (
    Bar,
    Credentials,
    Exchange,
    Funds,
    Instrument,
    InstrumentType,
    Position,
    Quote,
)

FAKE_INSTRUMENT = Instrument(
    symbol="RELIANCE",
    broker_symbol="RELIANCE",
    exchange=Exchange.NSE,
    broker_exchange="NSE",
    token="fake-738561",
    expiry=None,
    strike=None,
    lot_size=1,
    instrument_type=InstrumentType.EQ,
    tick_size=0.05,
)

FAKE_LAST_PRICE = 2500.0

# Two daily candles, stamped the way Kite stamps them (00:00 IST = 18:30 UTC the day before).
FAKE_BAR_TIMES = (
    datetime(2026, 9, 17, 18, 30, tzinfo=UTC),
    datetime(2026, 9, 18, 18, 30, tzinfo=UTC),
)


class FakeBrokerPort:
    def authenticate(self, request_token: str) -> Credentials:
        return Credentials(
            broker="fake",
            access_token="fake-access-token",
            refresh_token=None,
            expires_at=None,
        )

    def get_instrument_master(self) -> list[Instrument]:
        return [FAKE_INSTRUMENT]

    def get_quote(self, instrument: Instrument) -> Quote:
        return Quote(instrument=instrument, last_price=FAKE_LAST_PRICE, as_of=datetime.now(UTC))

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return [self.get_quote(instrument) for instrument in instruments]

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return [
            Bar(
                instrument=instrument,
                interval=interval,
                open=FAKE_LAST_PRICE,
                high=FAKE_LAST_PRICE + 10,
                low=FAKE_LAST_PRICE - 10,
                close=FAKE_LAST_PRICE + 5,
                volume=1000,
                timestamp=timestamp,
            )
            for timestamp in FAKE_BAR_TIMES
        ]

    def place_order(self, request: OrderRequest) -> OrderResult:
        return OrderResult(status=OrderStatus.PLACED, broker_order_id="fake-order-1", reason=None)

    def get_positions(self) -> list[Position]:
        return []

    def get_funds(self) -> Funds:
        return Funds(broker="fake", available_cash=0.0, used_margin=0.0)
