from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.exceptions import UnknownSignalError
from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import SignalFactory, get_signal_class, register_signal


@register_signal("fixed_value_for_test")
class _FixedValueSignal:
    name = "fixed_value_for_test"

    def __init__(self, value: float) -> None:
        self._value = value

    def compute(self, bars: list[Bar]) -> RawSignal:
        bar = bars[-1]
        return RawSignal(
            symbol=bar.symbol,
            interval=bar.interval,
            ts=bar.ts,
            name=self.name,
            value=self._value,
        )

    def scale(self, raw: RawSignal) -> Forecast:
        return Forecast(
            symbol=raw.symbol,
            interval=raw.interval,
            ts=raw.ts,
            name=raw.name,
            scaled_value=raw.value,
        )


def _bar() -> Bar:
    return Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
        provider="synthetic",
    )


def test_register_signal_decorator_registers_class() -> None:
    assert get_signal_class("fixed_value_for_test") is _FixedValueSignal


def test_get_signal_class_raises_unknown_signal_error_for_missing_name() -> None:
    with pytest.raises(UnknownSignalError):
        get_signal_class("nonexistent_signal")


def test_signal_factory_create_instantiates_with_config_kwargs() -> None:
    signal = SignalFactory.create("fixed_value_for_test", {"value": 42.0})
    bars = [_bar()]

    raw = signal.compute(bars)
    assert raw.value == 42.0
    assert raw.symbol == "RELIANCE"
    assert raw.name == "fixed_value_for_test"

    forecast = signal.scale(raw)
    assert forecast.scaled_value == 42.0
    assert forecast.symbol == "RELIANCE"
