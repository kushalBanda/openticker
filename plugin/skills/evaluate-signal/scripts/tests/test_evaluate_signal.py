import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "evaluate_signal.py"
_spec = importlib.util.spec_from_file_location("evaluate_signal_script", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
evaluate_signal_script = importlib.util.module_from_spec(_spec)
sys.modules["evaluate_signal_script"] = evaluate_signal_script
_spec.loader.exec_module(evaluate_signal_script)

from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="RELIANCE", interval="1d", ts=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000, provider="kite",
        )
        for i, c in enumerate(closes)
    ]


@pytest.mark.asyncio
async def test_run_returns_report_shape(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        evaluate_signal_script, "_resolve_provider", lambda provider: ("kite", {"api_key": "k", "access_token": "t"})
    )

    async def _fake_fetch_symbol_bars(store, provider, creds, symbol, interval, frm, to):  # type: ignore[no-untyped-def]
        return _bars([100.0 + i for i in range(40)])

    monkeypatch.setattr(evaluate_signal_script, "fetch_symbol_bars", _fake_fetch_symbol_bars)
    monkeypatch.setattr(evaluate_signal_script, "DuckDBStore", lambda: object())

    result = await evaluate_signal_script._run(
        signal="sma", symbol="RELIANCE", horizon=1, min_lookback=3,
        params={"window": 3}, interval="1d", days=365, provider="kite",
    )

    assert result["signal_name"] == "sma"
    assert "information_coefficient" in result
    assert "effective_ic_p_value" in result
    assert "overlapping_windows_caveat" in result
