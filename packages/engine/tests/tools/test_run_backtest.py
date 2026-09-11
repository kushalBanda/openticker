from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from engine.core.exceptions import InvalidStrategyParamsError
from engine.tools.run_backtest import run_backtest
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from strategy.core.exceptions import UnknownStrategyError
from strategy.metrics.performance import PerformanceReport


def _bar(day: int, close: float, symbol: str = "RELIANCE") -> Bar:
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="kite",
    )


@pytest.mark.asyncio
async def test_run_backtest_returns_performance_report() -> None:
    bars = [_bar(1, 100.0), _bar(2, 110.0)]
    fake_portfolio = Mock(
        cash=99_000.0,
        positions={"RELIANCE": 10},
        equity_curve=[(bars[0].ts, 100_000.0), (bars[1].ts, 101_000.0)],
    )
    report = PerformanceReport(
        total_return=0.01,
        annualized_return=0.5,
        max_drawdown=0.0,
        sharpe_ratio=1.2,
        exponential_std=0.02,
        win_rate=1.0,
    )

    with (
        patch(
            "engine.tools.run_backtest.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.run_backtest.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch("engine.tools.run_backtest.StrategyFactory") as mock_factory,
        patch("engine.tools.run_backtest.BacktestEngine") as mock_engine_cls,
        patch("engine.tools.run_backtest.compute_metrics", return_value=report),
    ):
        mock_engine_cls.return_value.run = AsyncMock(return_value=fake_portfolio)
        result = await run_backtest(
            strategy="sma_cross",
            symbols=["RELIANCE"],
            params={"long_window": 20, "quantity": 10},
            provider="kite",
        )

    mock_factory.create.assert_called_once_with("sma_cross", {"long_window": 20, "quantity": 10})
    assert result["provider"] == "kite"
    assert result["strategy"] == "sma_cross"
    assert result["performance"]["sharpe_ratio"] == 1.2
    assert result["ending_cash"] == 99_000.0
    assert result["ending_equity"] == 101_000.0
    assert result["positions"] == {"RELIANCE": 10}


@pytest.mark.asyncio
async def test_run_backtest_defaults_params_to_empty_dict() -> None:
    bars = [_bar(1, 100.0)]
    fake_portfolio = Mock(cash=100_000.0, positions={}, equity_curve=[])
    report = PerformanceReport(
        total_return=0.0,
        annualized_return=0.0,
        max_drawdown=0.0,
        sharpe_ratio=0.0,
        exponential_std=0.0,
        win_rate=0.0,
    )

    with (
        patch(
            "engine.tools.run_backtest.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.run_backtest.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch("engine.tools.run_backtest.StrategyFactory") as mock_factory,
        patch("engine.tools.run_backtest.BacktestEngine") as mock_engine_cls,
        patch("engine.tools.run_backtest.compute_metrics", return_value=report),
    ):
        mock_engine_cls.return_value.run = AsyncMock(return_value=fake_portfolio)
        await run_backtest(strategy="buy_and_hold", symbols=["RELIANCE"])

    mock_factory.create.assert_called_once_with("buy_and_hold", {})


@pytest.mark.asyncio
async def test_run_backtest_returns_degraded_note_on_insufficient_data() -> None:
    bars = [_bar(1, 100.0)]
    fake_portfolio = Mock(
        cash=100_000.0,
        positions={},
        equity_curve=[(bars[0].ts, 100_000.0)],
    )

    with (
        patch(
            "engine.tools.run_backtest.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.run_backtest.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch("engine.tools.run_backtest.StrategyFactory"),
        patch("engine.tools.run_backtest.BacktestEngine") as mock_engine_cls,
        patch(
            "engine.tools.run_backtest.compute_metrics",
            side_effect=InsufficientDataError("too few points"),
        ),
    ):
        mock_engine_cls.return_value.run = AsyncMock(return_value=fake_portfolio)
        result = await run_backtest(strategy="buy_and_hold", symbols=["RELIANCE"])

    assert result["performance"] is None
    assert "performance_note" in result
    assert "too few points" in result["performance_note"]
    assert result["ending_equity"] == 100_000.0


@pytest.mark.asyncio
async def test_run_backtest_falls_back_to_cash_when_equity_curve_empty() -> None:
    bars = [_bar(1, 100.0)]
    fake_portfolio = Mock(cash=100_000.0, positions={}, equity_curve=[])

    with (
        patch(
            "engine.tools.run_backtest.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.run_backtest.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch("engine.tools.run_backtest.StrategyFactory"),
        patch("engine.tools.run_backtest.BacktestEngine") as mock_engine_cls,
        patch(
            "engine.tools.run_backtest.compute_metrics",
            side_effect=InsufficientDataError("no equity points"),
        ),
    ):
        mock_engine_cls.return_value.run = AsyncMock(return_value=fake_portfolio)
        result = await run_backtest(strategy="buy_and_hold", symbols=["RELIANCE"])

    assert result["ending_equity"] == 100_000.0


@pytest.mark.asyncio
async def test_run_backtest_translates_unknown_strategy_error() -> None:
    with (
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch(
            "engine.tools.run_backtest.StrategyFactory.create",
            side_effect=UnknownStrategyError("no strategy registered for name 'nope'"),
        ),
        patch("engine.tools.run_backtest.list_strategy_names", return_value=["sma_cross"]),
        pytest.raises(UnknownStrategyError, match="sma_cross"),
    ):
        await run_backtest(strategy="nope", symbols=["RELIANCE"])


@pytest.mark.asyncio
async def test_run_backtest_translates_bad_params_to_engine_error() -> None:
    with (
        patch("engine.tools.run_backtest.ensure_strategies_registered"),
        patch(
            "engine.tools.run_backtest.StrategyFactory.create",
            side_effect=TypeError("__init__() got an unexpected keyword argument 'bogus'"),
        ),
        pytest.raises(InvalidStrategyParamsError, match="sma_cross"),
    ):
        await run_backtest(strategy="sma_cross", symbols=["RELIANCE"], params={"bogus": 1})
