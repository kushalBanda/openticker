from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.sma_cross.strategy import SmaCrossStrategy


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


async def test_goes_long_when_price_crosses_above_trend_sma() -> None:
    closes = [100.0] * 20 + [110.0, 120.0, 130.0, 140.0, 150.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = SmaCrossStrategy(long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10


async def test_goes_flat_when_price_crosses_below_trend_sma_never_shorts() -> None:
    # Flat, then price rises above trend SMA (go long), then falls back
    # below it (Faber's rule exits to cash, it never opens a short leg).
    closes = (
        [100.0] * 20
        + [110.0, 120.0, 130.0, 140.0, 150.0]
        + [140.0, 130.0, 120.0, 110.0, 100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
    )
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = SmaCrossStrategy(long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 0


async def test_tracks_two_symbols_independently() -> None:
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

    strategy = SmaCrossStrategy(long_window=20, quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10
    assert result.positions.get("NSE-TCS", 0) == 0


async def test_volatility_targeted_sizing_enters_nonzero_quantity() -> None:
    closes = [100.0] * 20 + [110.0, 120.0, 130.0, 140.0, 150.0]
    bars = {"NSE-RELIANCE": [_bar(i, c) for i, c in enumerate(closes)]}

    strategy = SmaCrossStrategy(long_window=20, target_risk_pct=0.02, vol_window=19)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) > 0


def test_rejects_both_quantity_and_target_risk_pct() -> None:
    try:
        SmaCrossStrategy(long_window=20, quantity=10, target_risk_pct=0.02, vol_window=20)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_rejects_neither_quantity_nor_target_risk_pct() -> None:
    try:
        SmaCrossStrategy(long_window=20)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
