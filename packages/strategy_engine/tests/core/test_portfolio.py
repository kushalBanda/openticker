from datetime import UTC, datetime

from data_engine.core.models import Bar
from strategy_engine.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy_engine.core.models import Fill, Order
from strategy_engine.core.portfolio import Portfolio


def _fill(side: str, quantity: int, fill_price: float, commission: float = 0.0) -> Fill:
    order = Order(
        symbol="NSE-RELIANCE",
        side=side,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return Fill(
        order=order,
        fill_price=fill_price,
        fill_ts=datetime(2026, 1, 2, tzinfo=UTC),
        commission=commission,
    )


def test_apply_fills_updates_cash_and_positions() -> None:
    portfolio = Portfolio(starting_cash=1000.0)

    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0, commission=2.0)])

    assert portfolio.cash == 1000.0 - (5 * 10.0) - 2.0
    assert portfolio.positions["NSE-RELIANCE"] == 5


def test_apply_fills_sell_reduces_position_increases_cash() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])

    portfolio.apply_fills([_fill(ORDER_SIDE_SELL, quantity=3, fill_price=12.0, commission=1.0)])

    assert portfolio.positions["NSE-RELIANCE"] == 2
    assert portfolio.cash == 1000.0 - 50.0 + 36.0 - 1.0


def test_mark_to_market_appends_equity_curve_point() -> None:
    portfolio = Portfolio(starting_cash=1000.0)
    portfolio.apply_fills([_fill(ORDER_SIDE_BUY, quantity=5, fill_price=10.0)])
    bar = Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 3, tzinfo=UTC),
        open=11.0,
        high=11.0,
        low=11.0,
        close=11.0,
        volume=1000,
        provider="test",
    )

    portfolio.mark_to_market(bar)

    assert len(portfolio.equity_curve) == 1
    ts, value = portfolio.equity_curve[0]
    assert ts == bar.ts
    assert value == (1000.0 - 50.0) + (5 * 11.0)
