"""write_bars, get_bars — historical OHLCV, keyed by (exchange, symbol, interval, timestamp).

All-or-nothing: `write_bars` validates the whole batch before touching the
table and writes it in one transaction, so a bad batch leaves nothing behind
rather than a partial range.
"""

from datetime import UTC, date, datetime, time, timedelta

from openticker.ports.models import EXCHANGE_TIMEZONE, Bar, Instrument
from openticker.storage.duckdb.engine import get_connection


class InvalidBarsError(ValueError):
    """A batch of bars can't be stored as given; nothing was written."""


def write_bars(rows: list[Bar]) -> None:
    """Insert, or overwrite bars already stored for the same key (re-fetching a
    range is idempotent)."""
    for bar in rows:
        if bar.timestamp.tzinfo is None:
            raise InvalidBarsError(f"bar at {bar.timestamp} is naive; timestamps must be tz-aware")
    if not rows:
        return
    records = [
        (
            bar.instrument.exchange.value,
            bar.instrument.symbol,
            bar.interval,
            bar.timestamp.astimezone(UTC).replace(tzinfo=None),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
        )
        for bar in rows
    ]
    with get_connection() as connection:
        connection.begin()
        try:
            connection.executemany(
                "INSERT OR REPLACE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", records
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()


def get_bars(instrument: Instrument, interval: str, start: date, end: date) -> list[Bar]:
    """Stored bars from `start` through `end` (exchange-local trading dates),
    inclusive, oldest first. Nothing stored returns `[]`."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume FROM bars
            WHERE exchange = ? AND symbol = ? AND interval = ?
              AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp
            """,
            [
                instrument.exchange.value,
                instrument.symbol,
                interval,
                _utc_naive(start),
                _utc_naive(end + timedelta(days=1)),
            ],
        ).fetchall()
    return [
        Bar(
            instrument=instrument,
            interval=interval,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            timestamp=timestamp.replace(tzinfo=UTC),
        )
        for timestamp, open_, high, low, close, volume in rows
    ]


def _utc_naive(day: date) -> datetime:
    """Midnight of `day` on the exchange's clock, as the naive UTC the table stores.
    A daily candle for 2026-09-18 is stamped 00:00 IST — 2026-09-17 in UTC — so
    filtering on UTC dates would miss it."""
    midnight = datetime.combine(day, time.min, tzinfo=EXCHANGE_TIMEZONE)
    return midnight.astimezone(UTC).replace(tzinfo=None)
