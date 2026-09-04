from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.strategies.buy_and_hold.strategy import BuyAndHoldStrategy


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


async def test_buys_once_on_first_bar_and_never_trades_again() -> None:
    closes = [100.0, 110.0, 90.0, 120.0, 80.0]
    bars = {"NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(closes)]}

    strategy = BuyAndHoldStrategy(quantity=10)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 10
    assert len(portfolio.ledger.entries) == 1


async def test_buys_every_symbol_in_basket_independently() -> None:
    reliance_closes = [100.0, 110.0, 120.0]
    tcs_closes = [200.0, 190.0, 210.0]
    bars = {
        "NSE-RELIANCE": [_bar("NSE-RELIANCE", i, c) for i, c in enumerate(reliance_closes)],
        "NSE-TCS": [_bar("NSE-TCS", i, c) for i, c in enumerate(tcs_closes)],
    }

    strategy = BuyAndHoldStrategy(quantity=5)
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    engine = BacktestEngine(broker, portfolio)

    result = await engine.run(bars, strategy)

    assert result.positions.get("NSE-RELIANCE", 0) == 5
    assert result.positions.get("NSE-TCS", 0) == 5
    assert len(portfolio.ledger.entries) == 2
