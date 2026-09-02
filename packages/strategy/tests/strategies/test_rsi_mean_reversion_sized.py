from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.rsi_mean_reversion_sized.strategy import (
    RsiMeanReversionSizedStrategy,
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


def test_generates_buy_signal_when_oversold_with_sized_quantity() -> None:
    closes = [100.0 - i for i in range(20)]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = RsiMeanReversionSizedStrategy(
        period=14, oversold=30.0, overbought=70.0, target_risk_pct=0.02
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    # Sizing depends on volatility/price, not a fixed number — assert a
    # position was taken at all, not an exact share count.
    assert result.positions.get("NSE-RELIANCE", 0) > 0


def test_higher_risk_budget_produces_larger_position() -> None:
    closes = [100.0 - i for i in range(20)]

    def run(target_risk_pct: float) -> int:
        bars = [_bar(i, c) for i, c in enumerate(closes)]
        strategy = RsiMeanReversionSizedStrategy(
            period=14, oversold=30.0, overbought=70.0, target_risk_pct=target_risk_pct
        )
        broker = BacktestBroker()
        portfolio = Portfolio(starting_cash=100_000.0)
        engine = BacktestEngine(broker, portfolio)
        result = engine.run(bars, strategy)
        return result.positions.get("NSE-RELIANCE", 0)

    low_risk_position = run(target_risk_pct=0.01)
    high_risk_position = run(target_risk_pct=0.10)

    assert high_risk_position > low_risk_position


def test_no_position_taken_on_flat_prices() -> None:
    # Flat closes give simple_rsi's avg_loss == 0 branch (RSI = 100), never
    # below oversold, so no trade — also incidentally confirms the
    # strategy doesn't crash on zero realized volatility, though that
    # guard is unreachable via this path since a flat window can't be
    # both oversold and zero-variance under simple_rsi's formula.
    closes = [100.0] * 20
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    strategy = RsiMeanReversionSizedStrategy(
        period=14, oversold=30.0, overbought=70.0, target_risk_pct=0.02
    )
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 0
