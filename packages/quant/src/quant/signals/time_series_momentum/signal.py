from ingest.core.models import Bar

from quant.core.constants import FORECAST_SCALE_MAX
from quant.core.exceptions import InsufficientDataError
from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import register_signal
from quant.core.series import bar_closes_to_series


@register_signal("time_series_momentum")
class TimeSeriesMomentumSignal:
    """Moskowitz, Ooi & Pedersen (2012) time-series momentum: sign of an
    instrument's own trailing `window`-bar return, independent of any
    other instrument (no cross-sectional ranking). `value` is +1.0 (go
    long), -1.0 (go short), or 0.0 (flat, on a flat trailing return) —
    the paper's raw signal is the trailing return itself, but every
    consumer here (strategy entry direction, forecast conviction) only
    ever needs its sign, so the sign is what this computes, not the
    unscaled return magnitude.
    """

    name = "time_series_momentum"

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be greater than 0")
        self._window = window

    def compute(self, bars: list[Bar]) -> RawSignal:
        if len(bars) < self._window + 1:
            raise InsufficientDataError(
                f"time_series_momentum needs at least {self._window + 1} bars, got {len(bars)}"
            )
        closes = bar_closes_to_series(bars)
        trailing_return = float(closes.iloc[-1] / closes.iloc[-1 - self._window] - 1)
        value = 0.0 if trailing_return == 0 else (1.0 if trailing_return > 0 else -1.0)
        last = bars[-1]
        return RawSignal(
            symbol=last.symbol,
            interval=last.interval,
            ts=last.ts,
            name=self.name,
            value=value,
        )

    def scale(self, raw: RawSignal) -> Forecast:
        # Sign is already full conviction one way or the other (or none,
        # if flat) — no graded strength to preserve, so scale straight to
        # the forecast extremes rather than a linear map like RSI's.
        return Forecast(
            symbol=raw.symbol,
            interval=raw.interval,
            ts=raw.ts,
            name=raw.name,
            scaled_value=raw.value * FORECAST_SCALE_MAX,
        )
