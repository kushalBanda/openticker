from ingest.core.models import Bar

from quant.core.constants import FORECAST_SCALE_MAX, RSI_MIDPOINT
from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import register_signal
from quant.core.series import bar_closes_to_series
from quant.features.technicals import relative_strength_index


@register_signal("rsi")
class RsiSignal:
    name = "rsi"

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be greater than 0")
        self._period = period

    def compute(self, bars: list[Bar]) -> RawSignal:
        closes = bar_closes_to_series(bars)
        value = float(relative_strength_index(closes, self._period).iloc[-1])
        last = bars[-1]
        return RawSignal(
            symbol=last.symbol,
            interval=last.interval,
            ts=last.ts,
            name=self.name,
            value=value,
        )

    def scale(self, raw: RawSignal) -> Forecast:
        scaled = (raw.value - RSI_MIDPOINT) * (FORECAST_SCALE_MAX / RSI_MIDPOINT)
        return Forecast(
            symbol=raw.symbol,
            interval=raw.interval,
            ts=raw.ts,
            name=raw.name,
            scaled_value=scaled,
        )
