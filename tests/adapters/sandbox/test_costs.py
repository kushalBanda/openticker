"""Paper fills pay the book and the charges (ADR 28 in docs/adr), with the
shipped rates and the default of one tick of slippage when there is no book."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Exchange, Instrument, InstrumentType, Product, Quote, Side
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.models import SandboxTradeRow
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
CRUDE = replace(
    FAKE_INSTRUMENT,
    symbol="CRUDEOIL19OCT26FUT",
    broker_symbol="CRUDEOIL26OCTFUT",
    exchange=Exchange.MCX,
    broker_exchange="MCX",
    instrument_type=InstrumentType.FUT,
    expiry=date(2026, 10, 19),
)


class BookedBroker(PricedBroker):
    """Quotes with a bid and an ask either side of the last price."""

    def __init__(self, price: float, spread: float) -> None:
        super().__init__(price)
        self.spread = spread

    def get_quote(self, instrument: Instrument) -> Quote:
        quote = super().get_quote(instrument)
        half = self.spread / 2
        return replace(quote, bid=quote.last_price - half, ask=quote.last_price + half)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT, CRUDE])


def _sandbox(market: PricedBroker) -> SandboxBroker:
    return SandboxBroker("fake", market, SandboxSettings(), lambda: NOW)


def _order(
    side: Side,
    quantity: int = 10,
    kind: OrderType = OrderType.MARKET,
    price: float | None = None,
    instrument: Instrument = FAKE_INSTRUMENT,
    product: Product = Product.MIS,
) -> OrderRequest:
    return OrderRequest(instrument, side, quantity, product, kind, price, "mcp")


def test_a_market_buy_pays_the_ask_and_its_charges_come_out_of_cash() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))

    result = sandbox.place_order(_order(Side.BUY))

    [trade] = sandbox.get_trades(NOW, 5)
    funds = sandbox.get_funds()
    assert result.fill_price == 1000.5
    assert trade.charges is not None and trade.charges > 0
    assert funds.charges == trade.charges
    assert funds.available_cash == pytest.approx(
        funds.total_capital - funds.used_margin - trade.charges
    )


def test_a_market_sell_gets_the_bid() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))

    assert sandbox.place_order(_order(Side.SELL)).fill_price == 999.5


def test_the_trade_keeps_the_price_the_order_was_placed_against() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))

    sandbox.place_order(_order(Side.BUY))

    [trade] = sandbox.get_trades(NOW, 5)
    assert (trade.price, trade.expected_price) == (1000.5, 1000.0)


def test_without_a_book_a_fill_moves_a_tick_against_the_order() -> None:
    sandbox = _sandbox(PricedBroker(1000.0))

    assert sandbox.place_order(_order(Side.BUY)).fill_price == 1000.05


def test_a_round_trip_loses_the_spread_and_both_sides_charges() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))

    sandbox.place_order(_order(Side.BUY))
    sandbox.place_order(_order(Side.SELL))

    funds = sandbox.get_funds()
    trades = sandbox.get_trades(NOW, 5)
    assert funds.realized_pnl == pytest.approx(-10.0)  # sold at 999.5, bought at 1000.5
    assert funds.charges == pytest.approx(sum(t.charges or 0 for t in trades))
    assert funds.available_cash == pytest.approx(funds.total_capital - 10.0 - funds.charges)


def test_a_resting_limit_fills_at_its_limit_and_pays_charges() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))
    placed = sandbox.place_order(_order(Side.BUY, kind=OrderType.LIMIT, price=990.0))
    assert placed.status is OrderStatus.PENDING
    [pending] = sandbox.pending_orders()

    result = sandbox.fill_pending(pending, 990.0, NOW)

    [trade] = sandbox.get_trades(NOW, 5)
    assert (result.fill_price, trade.expected_price) == (990.0, 990.0)
    assert trade.charges is not None and trade.charges > 0


def test_closing_a_position_sells_at_the_bid_and_pays_charges() -> None:
    market = BookedBroker(1000.0, spread=1.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY))

    result = sandbox.close_position(
        FAKE_INSTRUMENT, Product.MIS, market.get_quote(FAKE_INSTRUMENT), NOW, "mcp"
    )

    closing = sandbox.get_trades(NOW, 5)[0]
    assert result.fill_price == 999.5
    assert closing.charges is not None and closing.charges > 0


def test_expiry_settlement_pays_no_charges() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))
    sandbox.place_order(_order(Side.BUY))

    sandbox.settle_position(FAKE_INSTRUMENT, Product.MIS, 1000.0, "expired", NOW)

    settled = sandbox.get_trades(NOW, 5)[0]
    assert (settled.price, settled.charges, settled.charges_detail) == (1000.0, None, None)
    assert settled.realized_pnl == -5.0  # bought at the ask, 1000.5


def test_mcx_fills_carry_no_charges_until_its_contract_size_is_known() -> None:
    sandbox = _sandbox(BookedBroker(8900.0, spread=2.0))

    sandbox.place_order(_order(Side.BUY, quantity=1, instrument=CRUDE, product=Product.NRML))

    [trade] = sandbox.get_trades(NOW, 5)
    assert trade.charges is None and sandbox.get_funds().charges == 0.0


def test_trades_from_before_costs_read_as_such() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))
    sandbox.place_order(_order(Side.BUY))
    with Session(get_engine()) as session:
        session.query(SandboxTradeRow).update(
            {"charges": None, "expected_price": None, "realized_pnl": None, "charges_detail": None}
        )
        session.commit()

    [trade] = sandbox.get_trades(NOW, 5)

    assert (trade.charges, trade.expected_price) == (None, None)
    assert (trade.realized_pnl, trade.charges_detail) == (None, None)


def test_opening_fill_records_zero_realized() -> None:
    sandbox = _sandbox(BookedBroker(1000.0, spread=1.0))

    sandbox.place_order(_order(Side.BUY))

    [trade] = sandbox.get_trades(NOW, 5)
    assert trade.realized_pnl == 0.0


def test_closing_fill_records_realized_pnl_on_its_trade() -> None:
    market = BookedBroker(1000.0, spread=1.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY, quantity=10))  # at 1000.5
    market.price = 1100.0

    sandbox.place_order(_order(Side.SELL, quantity=4))  # at 1099.5
    placed = sandbox.place_order(_order(Side.SELL, quantity=6, kind=OrderType.LIMIT, price=1150))
    [pending] = sandbox.pending_orders()
    sandbox.fill_pending(pending, 1150.0, NOW)

    rest, first, opening = sandbox.get_trades(NOW, 5)
    assert placed.status is OrderStatus.PENDING
    assert (opening.realized_pnl, first.realized_pnl, rest.realized_pnl) == (0.0, 396.0, 897.0)
    assert sandbox.get_funds().realized_pnl == pytest.approx(396.0 + 897.0)


def test_fill_records_charges_breakdown_that_sums_to_total() -> None:
    market = BookedBroker(1000.0, spread=1.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY))

    sandbox.close_position(
        FAKE_INSTRUMENT, Product.MIS, market.get_quote(FAKE_INSTRUMENT), NOW, "mcp"
    )

    for trade in sandbox.get_trades(NOW, 5):
        assert trade.charges_detail is not None and trade.charges is not None
        assert {"brokerage", "transaction_tax", "gst"} <= set(trade.charges_detail)
        assert round(sum(trade.charges_detail.values()), 2) == trade.charges
