from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.sma_crossover.strategy import SmaCrossoverStrategy


def _bar(day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


async def test_generates_buy_signal_on_golden_cross() -> None:
    # Flat prices establish both SMAs equal (short below/equal long), then a
    # sharp rise pulls the short SMA above the long SMA, a golden cross.
    closes = [100.0] * 20 + [110.0, 120.0, 130.0, 140.0, 150.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = SmaCrossoverStrategy(short_window=5, long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10


async def test_migration_produces_identical_backtest_result_to_baseline() -> None:
    # Baseline captured from the pre-migration implementation (inline
    # deque[float] SMA math, before SmaSignal existed) against this exact
    # fixture: flat, then a golden cross (rise), then a death cross
    # (decline). Proves migrating to two SmaSignal instances (short/long
    # window) changed nothing about the strategy's actual behavior.
    closes = (
        [100.0] * 20
        + [110.0, 120.0, 130.0, 140.0, 150.0]
        + [140.0, 130.0, 120.0, 110.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
    )
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = SmaCrossoverStrategy(short_window=5, long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions == {"NSE-RELIANCE": 0}
    assert result.cash == 99600.0
    assert len(result.equity_curve) == 35
    assert result.equity_curve[-1] == (
        datetime(2026, 2, 4, tzinfo=UTC),
        99600.0,
    )


async def test_tracks_two_symbols_independently() -> None:
    # NSE-RELIANCE crosses golden immediately; NSE-TCS stays flat throughout,
    # so only RELIANCE should ever get an order.
    reliance_closes = [100.0] * 20 + [110.0, 120.0, 130.0, 140.0, 150.0]
    tcs_closes = [200.0] * 25

    def _sym_bar(symbol: str, day: int, close: float) -> Bar:
        bar = _bar(day, close)
        return Bar(
            symbol=symbol,
            interval=bar.interval,
            ts=bar.ts,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            provider=bar.provider,
        )

    bars = {
        "NSE-RELIANCE": [_sym_bar("NSE-RELIANCE", i, c) for i, c in enumerate(reliance_closes)],
        "NSE-TCS": [_sym_bar("NSE-TCS", i, c) for i, c in enumerate(tcs_closes)],
    }

    strategy = SmaCrossoverStrategy(short_window=5, long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10
    assert result.positions.get("NSE-TCS", 0) == 0
