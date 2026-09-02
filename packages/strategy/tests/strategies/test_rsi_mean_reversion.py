from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.rsi_mean_reversion.strategy import (
    RsiMeanReversionStrategy,
)


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


def test_generates_buy_signal_when_oversold() -> None:
    # A sustained decline drives average loss well above average gain,
    # pushing RSI below the oversold threshold.
    closes = [100.0 - i for i in range(20)]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = RsiMeanReversionStrategy(
        period=14, oversold=30.0, overbought=70.0, quantity=5
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 5


def test_migration_produces_identical_backtest_result_to_baseline() -> None:
    # Baseline captured from the pre-migration implementation (inline
    # deque[float] + _compute_rsi, before RsiSignal existed) against this
    # exact fixture: a decline (triggers BUY once oversold) followed by a
    # rise (triggers SELL once overbought). Proves the migration to
    # RsiSignal changed nothing about the strategy's actual behavior.
    closes = [100.0 - i for i in range(20)] + [80.0 + i * 2 for i in range(20)]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = RsiMeanReversionStrategy(
        period=14, oversold=30.0, overbought=70.0, quantity=5
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert result.positions == {"NSE-RELIANCE": 0}
    assert result.cash == 100065.0
    assert len(result.equity_curve) == 40
    assert result.equity_curve[-1][1] == 100065.0
    assert result.equity_curve[0] == (
        datetime(2026, 1, 1, tzinfo=UTC),
        100000.0,
    )
