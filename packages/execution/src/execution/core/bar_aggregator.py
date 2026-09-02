from datetime import datetime, timedelta

from ingest.core.models import Bar, Tick

from execution.core.constants import INTERVAL_MINUTES


class TickBarAggregator:
    """Rolls live ticks up into Bars of a fixed interval width. Shared by
    PaperBroker's caller today and LiveBroker's caller later — one
    aggregation implementation, not one per broker (see
    docs/plans/execution-engine/03-program-design.md decision #3).
    """

    def __init__(self, interval: str) -> None:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"unsupported interval {interval!r}")
        self._interval = interval
        self._bucket_width = timedelta(minutes=INTERVAL_MINUTES[interval])
        self._bucket_start: datetime | None = None
        self._open: float = 0.0
        self._high: float = 0.0
        self._low: float = 0.0
        self._close: float = 0.0
        self._volume: int = 0
        self._symbol: str = ""
        self._provider: str = ""

    def _bucket_start_for(self, ts: datetime) -> datetime:
        epoch = datetime(ts.year, ts.month, ts.day, tzinfo=ts.tzinfo)
        elapsed = ts - epoch
        bucket_index = elapsed // self._bucket_width
        return epoch + bucket_index * self._bucket_width

    def add_tick(self, tick: Tick) -> Bar | None:
        bucket_start = self._bucket_start_for(tick.ts)

        if self._bucket_start is None:
            self._start_bucket(tick, bucket_start)
            return None

        if bucket_start == self._bucket_start:
            self._high = max(self._high, tick.price)
            self._low = min(self._low, tick.price)
            self._close = tick.price
            self._volume += tick.volume
            return None

        completed = self._build_bar(self._bucket_start)
        self._start_bucket(tick, bucket_start)
        return completed

    def flush(self) -> Bar | None:
        if self._bucket_start is None:
            return None
        completed = self._build_bar(self._bucket_start)
        self._bucket_start = None
        return completed

    def _start_bucket(self, tick: Tick, bucket_start: datetime) -> None:
        self._bucket_start = bucket_start
        self._symbol = tick.symbol
        self._provider = tick.provider
        self._open = tick.price
        self._high = tick.price
        self._low = tick.price
        self._close = tick.price
        self._volume = tick.volume

    def _build_bar(self, bucket_start: datetime) -> Bar:
        return Bar(
            symbol=self._symbol,
            interval=self._interval,
            ts=bucket_start,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            provider=self._provider,
        )
