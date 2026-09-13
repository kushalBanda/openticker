import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPT_DIR))

from position_sizing import build_sizing_json


def test_build_sizing_json_shape() -> None:
    from lib.mechanics.models import Bar

    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar("TEST", "1d", start + timedelta(days=i), 20.0, 21.0, 18.0, 20.0, 1000, "test")
        for i in range(10)
    ]
    result = build_sizing_json(bars, capital=100_000.0, risk_per_trade_pct=1.0, reward_risk_ratio=2.0)
    assert result["entry_price"] == 20.0
    assert result["stop_distance"] == 2.0
    assert result["stop_price"] == 18.0
    assert result["take_profit"] == 24.0
    assert result["quantity"] == 500
