from ingest.core.models import Bar

from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import register_signal
from quant.core.series import bar_closes_to_series
from quant.features.technicals import moving_average


@register_signal("sma")
class SmaSignal:
    name = "sma"

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be greater than 0")
        self._window = window

    def compute(self, bars: list[Bar]) -> RawSignal:
        closes = bar_closes_to_series(bars)
        value = float(moving_average(closes, self._window).iloc[-1])
        last = bars[-1]
        return RawSignal(
            symbol=last.symbol,
            interval=last.interval,
            ts=last.ts,
            name=self.name,
            value=value,
        )

    def scale(self, raw: RawSignal) -> Forecast:
        # A moving average is a raw price level, not a bounded ratio like
        # RSI's 0..100 — there is no natural -20..+20 mapping without a
        # reference price to compare it against. This is a documented
        # pass-through, not a real scaling function, until something
        # actually needs to compare this signal against others on the
        # forecast scale (see quant-research-layer plan for RSI's contrast:
        # its 0..100 range makes a real linear scale possible).
        return Forecast(
            symbol=raw.symbol,
            interval=raw.interval,
            ts=raw.ts,
            name=raw.name,
            scaled_value=raw.value,
        )
