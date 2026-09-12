from datetime import UTC, datetime

import pytest

from lib.math.models import Fill, Order
from lib.math.portfolio import Portfolio


def _order(symbol: str, side: str, quantity: int) -> Order:
    return Order(symbol=symbol, side=side, quantity=quantity, order_type="market", placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC))


def test_apply_fills_buy_then_sell_realizes_pnl() -> None:
    portfolio = Portfolio(starting_cash=100_000.0)
    portfolio.apply_fills(
        [Fill(order=_order("X", "buy", 10), fill_price=100.0, fill_ts=datetime(2026, 1, 1, tzinfo=UTC), commission=0.0)]
    )
    portfolio.apply_fills(
        [Fill(order=_order("X", "sell", 10), fill_price=110.0, fill_ts=datetime(2026, 1, 2, tzinfo=UTC), commission=0.0)]
    )
    assert portfolio.ledger.entries[-1].realized_pnl == pytest.approx(100.0)


def test_apply_fills_rejects_unknown_side() -> None:
    portfolio = Portfolio(starting_cash=100_000.0)
    with pytest.raises(ValueError, match="unknown order side"):
        portfolio.apply_fills(
            [Fill(order=_order("X", "hold", 10), fill_price=100.0, fill_ts=datetime(2026, 1, 1, tzinfo=UTC), commission=0.0)]
        )
