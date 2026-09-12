from datetime import UTC, datetime, timedelta

from lib.math.evaluation import evaluate_signal_ic
from lib.math.types import RawSignal
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="X", interval="1d", ts=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000, provider="kite",
        )
        for i, c in enumerate(closes)
    ]


def test_evaluate_signal_ic_perfect_correlation_gives_ic_near_one() -> None:
    closes = [100.0 + i for i in range(45)]
    bars = _bars(closes)

    def compute(window: list[Bar]) -> RawSignal:
        last = window[-1]
        return RawSignal(symbol=last.symbol, interval=last.interval, ts=last.ts, name="stub", value=last.close)

    report = evaluate_signal_ic(compute, "stub", bars, horizon=1, min_lookback=1)
    # Monotonically increasing closes give a monotonically decreasing
    # forward return (1/close shrinks as close grows) - a perfect
    # monotonic relationship, so |IC| should be near 1 regardless of sign.
    assert abs(report.information_coefficient) > 0.99
    assert report.sample_size == 44
