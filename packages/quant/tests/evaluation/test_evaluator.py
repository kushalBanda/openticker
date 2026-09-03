from datetime import UTC, datetime, timedelta

import pytest
from ingest.core.models import Bar
from quant.core.constants import MIN_SAMPLE_SIZE
from quant.core.exceptions import InsufficientDataError
from quant.core.interfaces import Forecast, RawSignal
from quant.evaluation.evaluator import evaluate_signal

MIN_LOOKBACK = 1
HORIZON = 1


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=base + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
            provider="kite",
        )
        for i, close in enumerate(closes)
    ]


class _PerfectSignal:
    """Reads the known next-bar return straight off the bars — a synthetic
    test double that should score a near-perfect IC. Not RSI/SMA."""

    name = "perfect"

    def compute(self, bars: list[Bar]) -> RawSignal:
        last = bars[-1]
        if len(bars) < 2:
            value = 0.0
        else:
            value = last.close / bars[-2].close - 1  # yesterday's pct return
        return RawSignal(
            symbol=last.symbol, interval=last.interval, ts=last.ts, name=self.name, value=value
        )

    def scale(self, raw: RawSignal) -> Forecast:
        return Forecast(
            symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value
        )


class _RandomSignal:
    """Deterministic pseudo-random value per bar, uncorrelated with returns."""

    name = "random"

    def __init__(self) -> None:
        self._rng = __import__("random").Random(42)

    def compute(self, bars: list[Bar]) -> RawSignal:
        last = bars[-1]
        return RawSignal(
            symbol=last.symbol,
            interval=last.interval,
            ts=last.ts,
            name=self.name,
            value=self._rng.uniform(-1, 1),
        )

    def scale(self, raw: RawSignal) -> Forecast:
        return Forecast(
            symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value
        )


class _ConstantSignal:
    name = "constant"

    def compute(self, bars: list[Bar]) -> RawSignal:
        last = bars[-1]
        return RawSignal(
            symbol=last.symbol, interval=last.interval, ts=last.ts, name=self.name, value=1.0
        )

    def scale(self, raw: RawSignal) -> Forecast:
        return Forecast(
            symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value
        )


def _closes_trending(n: int) -> list[float]:
    return [100.0 + i * 0.37 for i in range(n)]


def test_evaluate_signal_perfect_correlation_gives_ic_near_one() -> None:
    # Monotonically increasing day-over-day PERCENTAGE returns: the signal
    # (yesterday's pct return) and the forward return (today's pct return)
    # both grow monotonically with i, so their ranks line up almost
    # perfectly, a genuine momentum-style predictive relationship.
    closes = [100.0]
    for i in range(70):
        daily_return = 0.001 * (i + 1)
        closes.append(closes[-1] * (1 + daily_return))
    bars = _bars(closes)

    report = evaluate_signal(_PerfectSignal(), bars, horizon=HORIZON, min_lookback=2)

    assert report.information_coefficient > 0.95


def test_evaluate_signal_random_signal_gives_ic_near_zero() -> None:
    bars = _bars(_closes_trending(60))

    report = evaluate_signal(_RandomSignal(), bars, horizon=HORIZON, min_lookback=MIN_LOOKBACK)

    assert abs(report.information_coefficient) < 0.3


def test_evaluate_signal_constant_signal_raises_insufficient_data() -> None:
    bars = _bars(_closes_trending(60))

    with pytest.raises(InsufficientDataError):
        evaluate_signal(_ConstantSignal(), bars, horizon=HORIZON, min_lookback=MIN_LOOKBACK)


def test_evaluate_signal_raises_on_insufficient_data() -> None:
    bars = _bars(_closes_trending(MIN_SAMPLE_SIZE))

    with pytest.raises(InsufficientDataError):
        evaluate_signal(_RandomSignal(), bars, horizon=HORIZON, min_lookback=MIN_LOOKBACK)


def test_evaluate_signal_effective_sample_size_is_sample_size_over_horizon() -> None:
    bars = _bars(_closes_trending(120))

    report = evaluate_signal(_RandomSignal(), bars, horizon=3, min_lookback=MIN_LOOKBACK)

    assert report.effective_sample_size == report.sample_size // 3


def test_evaluate_signal_overlapping_windows_caveat_always_present() -> None:
    bars = _bars(_closes_trending(60))

    report = evaluate_signal(_RandomSignal(), bars, horizon=HORIZON, min_lookback=MIN_LOOKBACK)

    assert report.overlapping_windows_caveat != ""


def test_evaluate_signal_turnover_proxy_high_for_slow_changing_signal() -> None:
    bars = _bars(_closes_trending(60))

    class _SlowSignal:
        name = "slow"

        def compute(self, window: list[Bar]) -> RawSignal:
            last = window[-1]
            # Steps once every 10 bars (via the bar's own index encoded
            # in its timestamp) instead of every bar, deliberately slow
            # changing so autocorrelation is high and turnover_proxy low.
            day_index = (last.ts - datetime(2026, 1, 1, tzinfo=UTC)).days
            value = float(day_index // 10)
            return RawSignal(
                symbol=last.symbol, interval=last.interval, ts=last.ts, name=self.name, value=value
            )

        def scale(self, raw: RawSignal) -> Forecast:
            return Forecast(
                symbol=raw.symbol,
                interval=raw.interval,
                ts=raw.ts,
                name=raw.name,
                scaled_value=raw.value,
            )

    report = evaluate_signal(_SlowSignal(), bars, horizon=HORIZON, min_lookback=MIN_LOOKBACK)

    assert report.turnover_proxy < 0.5
