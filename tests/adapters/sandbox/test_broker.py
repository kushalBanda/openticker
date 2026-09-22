import threading

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _order(side: Side, quantity: int, product: Product = Product.CNC) -> OrderRequest:
    return OrderRequest(
        FAKE_INSTRUMENT, side, quantity, product, OrderType.MARKET, None, "test", "s1", "r1"
    )


def _sandbox(market: PricedBroker, capital: float = 100_000.0) -> SandboxBroker:
    return SandboxBroker("fake", market, SandboxSettings(starting_capital=capital))


def test_market_order_fills_at_the_live_price_and_blocks_margin() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)

    result = sandbox.place_order(_order(Side.BUY, 10))

    assert (result.status, result.fill_price) == (OrderStatus.FILLED, 1000.0)
    funds = sandbox.get_funds()
    assert (funds.used_margin, funds.available_cash) == (10_000.0, 90_000.0)
    [position] = sandbox.get_positions()
    assert (position.quantity, position.average_price) == (10, 1000.0)


def test_selling_back_realizes_pnl_into_available_cash() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY, 10))

    market.price = 1100.0
    sandbox.place_order(_order(Side.SELL, 10))

    funds = sandbox.get_funds()
    assert (funds.used_margin, funds.realized_pnl, funds.available_cash) == (0.0, 1000.0, 101_000.0)
    [position] = sandbox.get_positions()
    assert (position.quantity, position.realized_pnl, position.unrealized_pnl) == (0, 1000.0, 0.0)


def test_open_position_is_valued_at_the_live_price() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.SELL, 10, Product.MIS))

    market.price = 990.0

    [position] = sandbox.get_positions()
    assert (position.quantity, position.unrealized_pnl) == (-10, 100.0)


def test_delivery_cannot_be_sold_short() -> None:
    result = _sandbox(PricedBroker()).place_order(_order(Side.SELL, 1))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "sold short" in result.reason


def test_insufficient_funds_is_rejected_and_recorded() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0), capital=5_000.0)

    result = sandbox.place_order(_order(Side.BUY, 10))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "insufficient sandbox funds" in result.reason
    [order] = sandbox.get_orderbook(10)
    assert (order.status, order.strategy_id, order.run_id) == (OrderStatus.REJECTED, "s1", "r1")
    assert sandbox.get_positions() == []


def test_closing_is_never_refused_for_lack_of_funds() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market, capital=10_000.0)
    sandbox.place_order(_order(Side.BUY, 50, Product.MIS))  # 5x: all 10,000 as margin

    market.price = 1.0  # a loss of 49,950: far more than the account holds
    result = sandbox.place_order(_order(Side.SELL, 50, Product.MIS))

    assert result.status is OrderStatus.FILLED
    assert sandbox.get_funds().available_cash == pytest.approx(-39_950.0)


def test_stale_quote_is_not_filled() -> None:
    market = PricedBroker(price=1047.6)
    market.day_range = (1262.0, 1290.0)

    result = _sandbox(market).place_order(_order(Side.BUY, 1))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "no fresh price" in result.reason


def test_concurrent_fills_keep_funds_consistent() -> None:
    sandbox = _sandbox(PricedBroker(price=100.0), capital=1_000_000.0)
    errors: list[BaseException] = []

    def buy() -> None:
        try:
            for _ in range(10):
                assert sandbox.place_order(_order(Side.BUY, 1)).status is OrderStatus.FILLED
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=buy) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    [position] = sandbox.get_positions()
    assert position.quantity == 40
    assert sandbox.get_funds().used_margin == pytest.approx(4_000.0)
