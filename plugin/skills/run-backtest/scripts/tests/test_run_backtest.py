import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "run_backtest.py"
_spec = importlib.util.spec_from_file_location("run_backtest_script", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
run_backtest_script = importlib.util.module_from_spec(_spec)
sys.modules["run_backtest_script"] = run_backtest_script
_spec.loader.exec_module(run_backtest_script)

from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(symbol="RELIANCE", interval="1d", ts=start + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1000, provider="kite")
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_run_returns_expected_report_shape(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        run_backtest_script, "_resolve_provider", lambda provider: ("kite", {"api_key": "k", "access_token": "t"})
    )

    async def _fake_fetch_symbol_bars(store, provider, creds, symbol, interval, frm, to):  # type: ignore[no-untyped-def]
        return _bars([100.0, 101.0, 102.0, 103.0, 104.0])

    monkeypatch.setattr(run_backtest_script, "fetch_symbol_bars", _fake_fetch_symbol_bars)
    monkeypatch.setattr(run_backtest_script, "DuckDBStore", lambda: object())

    result = await run_backtest_script._run(
        strategy="buy_and_hold",
        symbols=["RELIANCE"],
        params={"quantity": 10},
        interval="1d",
        days=365,
        cash=100_000.0,
        provider="kite",
        commission_per_share=0.0,
        slippage_bps=0.0,
        cost_profile="free",
    )

    assert result["strategy"] == "buy_and_hold"
    assert result["provider"] == "kite"
    assert "ending_equity" in result
    assert "costs" in result
    assert result["costs"]["profile"] == "free"
    assert "performance" in result
