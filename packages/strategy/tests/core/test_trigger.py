from datetime import UTC, datetime, timedelta

from ingest.core.models import Bar
from quant.signals.sma.signal import SmaSignal
from strategy.core.trigger import (
    BollingerRsiEntryTrigger,
    CrossoverTrigger,
    ThresholdTrigger,
)


def _bar(day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


def test_crossover_trigger_fires_up_on_golden_cross() -> None:
    trigger = CrossoverTrigger(
        fast=SmaSignal(window=2), slow=SmaSignal(window=4), direction="up", min_bars=4
    )
    closes = [100.0, 100.0, 100.0, 100.0, 110.0, 120.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    fired = [trigger.check("NSE-RELIANCE", bars[: i + 1]) for i in range(len(bars))]

    assert fired == [False, False, False, False, True, False]


def test_crossover_trigger_fires_down_on_death_cross() -> None:
    trigger = CrossoverTrigger(
        fast=SmaSignal(window=2), slow=SmaSignal(window=4), direction="down", min_bars=4
    )
    closes = [100.0, 100.0, 100.0, 100.0, 110.0, 120.0, 90.0, 80.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    fired = [trigger.check("NSE-RELIANCE", bars[: i + 1]) for i in range(len(bars))]

    assert fired.count(True) == 1
    assert True in fired[4:]


def test_crossover_trigger_does_not_fire_before_min_bars() -> None:
    trigger = CrossoverTrigger(
        fast=SmaSignal(window=2), slow=SmaSignal(window=4), direction="up", min_bars=4
    )
    bars = [_bar(i, c) for i, c in enumerate([100.0, 110.0, 120.0])]

    assert trigger.check("NSE-RELIANCE", bars) is False


def test_crossover_trigger_tracks_symbols_independently() -> None:
    trigger = CrossoverTrigger(
        fast=SmaSignal(window=2), slow=SmaSignal(window=4), direction="up", min_bars=4
    )
    flat_closes = [100.0] * 5
    rising_closes = [100.0, 100.0, 100.0, 100.0, 150.0]

    # First call per symbol only establishes the baseline relation, so
    # check both symbols at 4 bars, then again once each has 5.
    trigger.check("FLAT", [_bar(i, c) for i, c in enumerate(flat_closes[:4])])
    trigger.check("RISING", [_bar(i, c) for i, c in enumerate(rising_closes[:4])])

    flat_fired = trigger.check("FLAT", [_bar(i, c) for i, c in enumerate(flat_closes)])
    rising_fired = trigger.check("RISING", [_bar(i, c) for i, c in enumerate(rising_closes)])

    assert flat_fired is False
    assert rising_fired is True


def test_threshold_trigger_fires_above_level() -> None:
    trigger = ThresholdTrigger(signal=SmaSignal(window=2), level=105.0, direction="above")
    bars = [_bar(0, 100.0), _bar(1, 120.0)]

    assert trigger.check("NSE-RELIANCE", bars) is True


def test_threshold_trigger_fires_below_level() -> None:
    trigger = ThresholdTrigger(signal=SmaSignal(window=2), level=105.0, direction="below")
    bars = [_bar(0, 90.0), _bar(1, 80.0)]

    assert trigger.check("NSE-RELIANCE", bars) is True


def test_threshold_trigger_does_not_fire_when_condition_false() -> None:
    trigger = ThresholdTrigger(signal=SmaSignal(window=2), level=105.0, direction="above")
    bars = [_bar(0, 90.0), _bar(1, 80.0)]

    assert trigger.check("NSE-RELIANCE", bars) is False


def test_bollinger_rsi_entry_trigger_fires_long_on_oversold_break() -> None:
    trigger = BollingerRsiEntryTrigger(
        bb_window=10, bb_std=2.0, rsi_period=10, rsi_threshold=30.0, direction="long"
    )
    closes = [100.0] * 10 + [80.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    assert trigger.check("NSE-RELIANCE", bars) is True


def test_bollinger_rsi_entry_trigger_fires_short_on_overbought_break() -> None:
    trigger = BollingerRsiEntryTrigger(
        bb_window=10, bb_std=2.0, rsi_period=10, rsi_threshold=70.0, direction="short"
    )
    closes = [100.0] * 10 + [120.0]
    bars = [_bar(i, c) for i, c in enumerate(closes)]

    assert trigger.check("NSE-RELIANCE", bars) is True


def test_bollinger_rsi_entry_trigger_does_not_fire_before_min_bars() -> None:
    trigger = BollingerRsiEntryTrigger(
        bb_window=10, bb_std=2.0, rsi_period=10, rsi_threshold=30.0, direction="long"
    )
    bars = [_bar(i, c) for i, c in enumerate([100.0] * 5)]

    assert trigger.check("NSE-RELIANCE", bars) is False


def test_bollinger_rsi_entry_trigger_does_not_fire_inside_bands() -> None:
    trigger = BollingerRsiEntryTrigger(
        bb_window=10, bb_std=2.0, rsi_period=10, rsi_threshold=30.0, direction="long"
    )
    bars = [_bar(i, c) for i, c in enumerate([100.0, 101.0, 99.0, 100.5, 99.5] * 2 + [100.0])]

    assert trigger.check("NSE-RELIANCE", bars) is False
