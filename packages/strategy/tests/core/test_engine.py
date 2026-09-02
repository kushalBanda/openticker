from datetime import UTC, datetime

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.engine import BacktestEngine
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _bar(ts: datetime, open_: float, close: float) -> Bar:
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=ts,
        open=open_,
        high=max(open_, close),
        low=min(open_, close),
        close=close,
        volume=1000,
        provider="test",
    )


class BuyOnFirstBarStrategy:
    def __init__(self) -> None:
        self.on_bar_calls: list[Bar] = []

    def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        self.on_bar_calls.append(bar)
        if len(self.on_bar_calls) == 1:
            broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_BUY,
                    quantity=1,
                    order_type=ORDER_TYPE_MARKET,
                    placed_at_ts=bar.ts,
                )
            )


def test_engine_wires_end_to_end_with_next_bar_open_fill() -> None:
    bars = [
        _bar(datetime(2026, 1, 1, tzinfo=UTC), open_=100.0, close=105.0),
        _bar(datetime(2026, 1, 2, tzinfo=UTC), open_=110.0, close=108.0),
        _bar(datetime(2026, 1, 3, tzinfo=UTC), open_=112.0, close=115.0),
    ]
    strategy = BuyOnFirstBarStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=1000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert strategy.on_bar_calls == bars  # called once per bar, in sequence
    assert result.positions["NSE-RELIANCE"] == 1
    assert result.cash == 1000.0 - 110.0
    assert len(result.equity_curve) == 3


def test_engine_no_lookahead_order_not_filled_on_same_bar() -> None:
    bars = [
        _bar(datetime(2026, 1, 1, tzinfo=UTC), open_=100.0, close=105.0),
        _bar(datetime(2026, 1, 2, tzinfo=UTC), open_=110.0, close=108.0),
    ]
    strategy = BuyOnFirstBarStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=1000.0)
    engine = BacktestEngine(broker, portfolio)

    engine.run(bars[:1], strategy)

    assert portfolio.positions.get("NSE-RELIANCE", 0) == 0
