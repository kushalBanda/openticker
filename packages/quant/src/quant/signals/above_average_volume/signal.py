from ingest.core.models import Bar

from quant.core.interfaces import Forecast, RawSignal
from quant.core.registry import register_signal
from quant.features.rolling_stats import average_volume


@register_signal("above_average_volume")
class AboveAverageVolumeSignal:
    """From Swing_Trading.pdf: volume materially above its recent average,
    read as a potential near-term reversal signal. See
    docs/features/swing-trading-signals.md.
    """

    name = "above_average_volume"

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be greater than 0")
        self._window = window

    def compute(self, bars: list[Bar]) -> RawSignal:
        volumes = [b.volume for b in bars[:-1]]
        baseline = average_volume(volumes, self._window)
        last = bars[-1]
        value = (last.volume / baseline) - 1 if baseline != 0 else 0.0
        return RawSignal(
            symbol=last.symbol,
            interval=last.interval,
            ts=last.ts,
            name=self.name,
            value=value,
        )

    def scale(self, raw: RawSignal) -> Forecast:
        # Already a bounded ratio (volume/baseline - 1), no natural
        # -20..+20 scale to map it to. Documented pass-through, same as
        # SmaSignal.scale.
        return Forecast(
            symbol=raw.symbol,
            interval=raw.interval,
            ts=raw.ts,
            name=raw.name,
            scaled_value=raw.value,
        )
