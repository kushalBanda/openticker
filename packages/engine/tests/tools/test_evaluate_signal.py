from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from engine.tools.evaluate_signal import evaluate_signal
from ingest.core.models import Bar
from quant.evaluation.evaluator import SignalEvaluationReport


def _bar(day: int, close: float) -> Bar:
    return Bar(
        symbol="RELIANCE",
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
async def test_evaluate_signal_returns_serialized_report() -> None:
    bars = [_bar(i, 100.0 + i) for i in range(1, 40)]
    report = SignalEvaluationReport(
        signal_name="rsi",
        symbol="RELIANCE",
        interval="1d",
        horizon=5,
        sample_size=35,
        effective_sample_size=7,
        information_coefficient=0.42,
        ic_p_value=0.01,
        effective_ic_p_value=0.2,
        turnover_proxy=0.3,
        overlapping_windows_caveat="see docs",
    )

    with (
        patch(
            "engine.tools.evaluate_signal.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.evaluate_signal.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.evaluate_signal.SignalFactory") as mock_factory,
        patch("engine.tools.evaluate_signal.evaluate_signal_report", return_value=report) as mock_eval,
    ):
        result = await evaluate_signal(
            signal="rsi",
            symbol="RELIANCE",
            horizon=5,
            min_lookback=15,
            params={"period": 14},
            provider="kite",
        )

    mock_factory.create.assert_called_once_with("rsi", {"period": 14})
    mock_eval.assert_called_once()
    assert result["information_coefficient"] == 0.42
    assert result["signal_name"] == "rsi"
    assert result["overlapping_windows_caveat"] == "see docs"


@pytest.mark.asyncio
async def test_evaluate_signal_defaults_params_to_empty_dict() -> None:
    bars = [_bar(i, 100.0 + i) for i in range(1, 40)]
    report = SignalEvaluationReport(
        signal_name="above_average_volume",
        symbol="RELIANCE",
        interval="1d",
        horizon=3,
        sample_size=35,
        effective_sample_size=11,
        information_coefficient=0.1,
        ic_p_value=0.4,
        effective_ic_p_value=0.5,
        turnover_proxy=0.1,
        overlapping_windows_caveat="see docs",
    )

    with (
        patch(
            "engine.tools.evaluate_signal.connect_engine",
            new=AsyncMock(return_value=("kite", object())),
        ),
        patch("engine.tools.evaluate_signal.fetch_symbol_bars", new=AsyncMock(return_value=bars)),
        patch("engine.tools.evaluate_signal.SignalFactory") as mock_factory,
        patch("engine.tools.evaluate_signal.evaluate_signal_report", return_value=report),
    ):
        await evaluate_signal(
            signal="above_average_volume", symbol="RELIANCE", horizon=3, min_lookback=20
        )

    mock_factory.create.assert_called_once_with("above_average_volume", {})


@pytest.mark.asyncio
async def test_evaluate_signal_translates_bad_params_to_engine_error() -> None:
    from engine.core.exceptions import InvalidSignalParamsError

    with (
        patch(
            "engine.tools.evaluate_signal.SignalFactory.create",
            side_effect=TypeError("__init__() got an unexpected keyword argument 'window'"),
        ),
        pytest.raises(InvalidSignalParamsError, match="rsi"),
    ):
        await evaluate_signal(
            signal="rsi", symbol="RELIANCE", horizon=5, min_lookback=15, params={"window": 14}
        )
