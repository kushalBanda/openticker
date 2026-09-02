from ingest.core.models import Bar

from quant.core.constants import FORECAST_SCALE_MAX, RSI_MIDPOINT
from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import register_signal
from quant.features.rolling_stats import simple_rsi


@register_signal("rsi")
class RsiSignal:
    name = "rsi"

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be greater than 0")
        self._period = period

    def compute(self, bars: list[Bar]) -> RawSignal:
        closes = [b.close for b in bars]
        value = simple_rsi(closes, self._period)
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
