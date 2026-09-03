from datetime import UTC, datetime

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.engine import BacktestEngine
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _bar(symbol: str, ts: datetime, open_: float, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=ts,
        open=open_,
        high=max(open_, close),
        low=min(open_, close),
        close=close,
        volume=1000,
        provider="test",
    )


class BuyOnFirstBatchStrategy:
    def __init__(self) -> None:
        self.on_bar_calls: list[dict[str, Bar]] = []

    async def on_bar(
        self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker
    ) -> None:
        self.on_bar_calls.append(bars)
        if len(self.on_bar_calls) == 1:
            for symbol, bar in bars.items():
                await broker.submit_order(
                    Order(
                        symbol=symbol,
                        side=ORDER_SIDE_BUY,
                        quantity=1,
                        order_type=ORDER_TYPE_MARKET,
                        placed_at_ts=bar.ts,
                    )
                )


async def test_engine_wires_end_to_end_with_next_bar_open_fill() -> None:
    bars = {
        "NSE-RELIANCE": [
            _bar("NSE-RELIANCE", datetime(2026, 1, 1, tzinfo=UTC), open_=100.0, close=105.0),
            _bar("NSE-RELIANCE", datetime(2026, 1, 2, tzinfo=UTC), open_=110.0, close=108.0),
            _bar("NSE-RELIANCE", datetime(2026, 1, 3, tzinfo=UTC), open_=112.0, close=115.0),
        ]
    }
    strategy = BuyOnFirstBatchStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=1000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert [b["NSE-RELIANCE"] for b in strategy.on_bar_calls] == bars["NSE-RELIANCE"]
    assert result.positions["NSE-RELIANCE"] == 1
    assert result.cash == 1000.0 - 110.0
    assert len(result.equity_curve) == 3


async def test_engine_no_lookahead_order_not_filled_on_same_bar() -> None:
    bars = {
        "NSE-RELIANCE": [
            _bar("NSE-RELIANCE", datetime(2026, 1, 1, tzinfo=UTC), open_=100.0, close=105.0),
        ]
    }
    strategy = BuyOnFirstBatchStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=1000.0)
    engine = BacktestEngine(broker, portfolio)

    await engine.run(bars, strategy)

    assert portfolio.positions.get("NSE-RELIANCE", 0) == 0


async def test_engine_batches_two_symbols_by_shared_timestamp() -> None:
    ts1 = datetime(2026, 1, 1, tzinfo=UTC)
    ts2 = datetime(2026, 1, 2, tzinfo=UTC)
    bars = {
        "NSE-RELIANCE": [
            _bar("NSE-RELIANCE", ts1, open_=100.0, close=105.0),
            _bar("NSE-RELIANCE", ts2, open_=110.0, close=108.0),
        ],
        "NSE-TCS": [
            _bar("NSE-TCS", ts1, open_=200.0, close=202.0),
            _bar("NSE-TCS", ts2, open_=205.0, close=207.0),
        ],
    }
    strategy = BuyOnFirstBatchStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=10_000.0)
    engine = BacktestEngine(broker, portfolio)

    await engine.run(bars, strategy)

    assert len(strategy.on_bar_calls) == 2
    first_batch = strategy.on_bar_calls[0]
    assert set(first_batch.keys()) == {"NSE-RELIANCE", "NSE-TCS"}
    assert first_batch["NSE-RELIANCE"].ts == ts1
    assert first_batch["NSE-TCS"].ts == ts1
    assert portfolio.positions["NSE-RELIANCE"] == 1
    assert portfolio.positions["NSE-TCS"] == 1


async def test_engine_skips_missing_symbol_no_forward_fill() -> None:
    ts1 = datetime(2026, 1, 1, tzinfo=UTC)
    ts2 = datetime(2026, 1, 2, tzinfo=UTC)  # NSE-TCS has no bar here (gap/late listing)
    ts3 = datetime(2026, 1, 3, tzinfo=UTC)
    bars = {
        "NSE-RELIANCE": [
            _bar("NSE-RELIANCE", ts1, open_=100.0, close=105.0),
            _bar("NSE-RELIANCE", ts2, open_=110.0, close=108.0),
            _bar("NSE-RELIANCE", ts3, open_=112.0, close=115.0),
        ],
        "NSE-TCS": [
            _bar("NSE-TCS", ts1, open_=200.0, close=202.0),
            _bar("NSE-TCS", ts3, open_=205.0, close=207.0),
        ],
    }
    strategy = BuyOnFirstBatchStrategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=10_000.0)
    engine = BacktestEngine(broker, portfolio)

    await engine.run(bars, strategy)

    assert len(strategy.on_bar_calls) == 3
    assert set(strategy.on_bar_calls[1].keys()) == {"NSE-RELIANCE"}  # NSE-TCS absent this step
