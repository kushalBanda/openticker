"""FakeBrokerPort — a BrokerPort for tests. No network calls; fixed values."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from openticker.core.orders.models import Order, OrderChanges, OrderRequest, OrderResult, Trade
from openticker.ports.models import (
    Bar,
    Credentials,
    DepthLevel,
    Exchange,
    Funds,
    Instrument,
    InstrumentType,
    MarketDepth,
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

    def get_market_depth(self, instrument: Instrument) -> MarketDepth:
        """Two bids and one ask around FAKE_LAST_PRICE."""
        return MarketDepth(
            instrument=instrument,
            as_of=datetime.now(UTC),
            last_price=FAKE_LAST_PRICE,
            last_quantity=5,
            bids=(
                DepthLevel(FAKE_LAST_PRICE - 0.05, 10, 2),
                DepthLevel(FAKE_LAST_PRICE - 0.1, 40, 3),
            ),
            asks=(DepthLevel(FAKE_LAST_PRICE + 0.05, 25, 1),),
            total_buy_quantity=900,
            total_sell_quantity=700,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            open_interest=None,
        )

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

    # The order side is never reached: orders go through the sandbox, which
    # wraps this adapter for prices (ADR 11 in docs/adr).
    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError("live order placement is not implemented")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("live positions are not implemented")

    def get_funds(self) -> Funds:
        raise NotImplementedError("live funds are not implemented")

    def get_orderbook(self, limit: int) -> list[Order]:
        raise NotImplementedError("the live order book is not implemented")

    def get_order(self, order_id: str) -> Order | None:
        raise NotImplementedError("live order lookup is not implemented")

    def cancel_order(self, order_id: str) -> OrderResult:
        raise NotImplementedError("live order cancellation is not implemented")

    def modify_order(self, order_id: str, changes: OrderChanges) -> OrderResult:
        raise NotImplementedError("live order changes are not implemented")

    def get_trades(self, since: datetime, limit: int) -> list[Trade]:
        raise NotImplementedError("the live trade book is not implemented")
