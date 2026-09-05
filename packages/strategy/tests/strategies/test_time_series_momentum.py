from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.time_series_momentum.strategy import TimeSeriesMomentumStrategy


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


async def test_goes_long_on_positive_trailing_return() -> None:
    # Flat for `window` bars (zero trailing return, no trade), then a
    # sharp rise on the last bar forces a positive trailing return.
    closes = [100.0] * 20 + [150.0, 150.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = TimeSeriesMomentumStrategy(window=20, target_risk_pct=0.02, vol_window=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) > 0


async def test_goes_short_on_negative_trailing_return() -> None:
    closes = [100.0] * 20 + [50.0, 50.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = TimeSeriesMomentumStrategy(window=20, target_risk_pct=0.02, vol_window=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) < 0


async def test_flat_when_no_trailing_return_signal_yet() -> None:
    closes = [100.0] * 10
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = TimeSeriesMomentumStrategy(window=20, target_risk_pct=0.02, vol_window=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 0


async def test_only_rebalances_once_per_calendar_month() -> None:
    # window=5 lets the signal fire mid-month; two bars land in the same
    # month after the first rebalance so the position must stay fixed
    # (the sizer would otherwise resize it on the vol change).
    closes = [100.0] * 5 + [150.0, 160.0, 170.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = TimeSeriesMomentumStrategy(window=5, target_risk_pct=0.02, vol_window=3)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    # First rebalance opens a long; later bars in the same month must not
    # trigger any further order (checked indirectly: ledger has exactly
    # one fill for the whole run).
    assert result.positions.get("NSE-RELIANCE", 0) > 0
    assert len(result.ledger.entries) == 1


def test_rejects_vol_window_not_less_than_window_plus_one() -> None:
    try:
        TimeSeriesMomentumStrategy(window=20, target_risk_pct=0.02, vol_window=21)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
