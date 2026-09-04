from datetime import UTC, datetime, timedelta

import pytest
from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.mean_reversion.strategy import MeanReversionStrategy


def _bar(symbol: str, day: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


def _strategy(
    bb_window: int = 10,
    bb_std: float = 2.0,
    rsi_period: int = 10,
    rsi_buy_threshold: float = 30.0,
    rsi_sell_threshold: float = 70.0,
    quantity: int = 10,
) -> MeanReversionStrategy:
    return MeanReversionStrategy(
        bb_window=bb_window,
        bb_std=bb_std,
        rsi_period=rsi_period,
        rsi_buy_threshold=rsi_buy_threshold,
        rsi_sell_threshold=rsi_sell_threshold,
        quantity=quantity,
    )


async def test_enters_long_on_oversold_break_and_exits_at_middle_band() -> None:
    # Flat, then a sharp drop (oversold entry), then a recovery back
    # above the middle band (exit).
    closes = [100.0] * 10 + [80.0, 82.0, 90.0, 100.0, 105.0]
    bars = {"NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(closes)]}

    strategy = _strategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 0
    assert len(portfolio.ledger.entries) == 2
    assert portfolio.ledger.entries[0].side == "buy"
    assert portfolio.ledger.entries[1].side == "sell"


async def test_enters_short_on_overbought_break() -> None:
    closes = [100.0] * 10 + [120.0, 118.0]
    bars = {"NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(closes)]}

    strategy = _strategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == -10


async def test_no_trade_without_bb_and_rsi_agreement() -> None:
    closes = [100.0, 101.0, 99.0, 100.5, 99.5] * 2 + [100.0, 100.0, 100.0, 100.0]
    bars = {"NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(closes)]}

    strategy = _strategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 0
    assert len(portfolio.ledger.entries) == 0


def test_rejects_buy_threshold_not_below_sell_threshold() -> None:
    with pytest.raises(ValueError, match="rsi_buy_threshold"):
        _strategy(rsi_buy_threshold=70.0, rsi_sell_threshold=30.0)


async def test_tracks_two_symbols_independently() -> None:
    reliance_closes = [100.0] * 10 + [80.0, 82.0]
    # Small alternating noise, not dead-flat: a perfectly flat series makes
    # Bollinger bands zero-width and Wilder RSI saturate at 100 (no losses
    # ever recorded), which spuriously reads as overbought.
    tcs_closes = [200.0, 200.5, 199.5, 200.5, 199.5] * 2 + [200.0, 200.0]

    bars = {
        "NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(reliance_closes)],
        "NSE-TCS": [_bar("NSE-TCS", i, c) for i, c in enumerate(tcs_closes)],
    }

    strategy = _strategy()
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10
    assert result.positions.get("NSE-TCS", 0) == 0
