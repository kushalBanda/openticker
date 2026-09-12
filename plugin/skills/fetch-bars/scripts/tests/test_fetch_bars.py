import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "fetch_bars.py"
_spec = importlib.util.spec_from_file_location("fetch_bars_script", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
fetch_bars_script = importlib.util.module_from_spec(_spec)
sys.modules["fetch_bars_script"] = fetch_bars_script
_spec.loader.exec_module(fetch_bars_script)

from lib.mechanics.models import Bar


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(
        symbol="RELIANCE", interval="1d", ts=ts,
        open=close, high=close, low=close, close=close, volume=1000, provider="kite",
    )


@pytest.mark.asyncio
async def test_run_returns_expected_shape(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        fetch_bars_script, "_resolve_provider", lambda provider: ("kite", {"api_key": "k", "access_token": "t"})
    )

    class _StubStore:
        def find_missing_range(self, symbol, interval, frm, to):  # type: ignore[no-untyped-def]
            return []

        def query_bars(self, symbol, interval, frm, to):  # type: ignore[no-untyped-def]
            return [
                _bar(datetime(2026, 1, 1, tzinfo=UTC), 100.0),
                _bar(datetime(2026, 1, 2, tzinfo=UTC), 101.0),
            ]

    monkeypatch.setattr(fetch_bars_script, "DuckDBStore", lambda: _StubStore())

    result = await fetch_bars_script._run("RELIANCE", "1d", 365, "kite")

    assert result["provider"] == "kite"
    assert result["symbol"] == "RELIANCE"
    assert result["bar_count"] == 2
    assert result["first_close"] == 100.0
    assert result["last_close"] == 101.0
    assert len(result["bars"]) == 2
