"""Flat DuckDB store for OHLCV bars.

Ported from ingest.storage.duckdb_store.DuckDBStore. The ticks and
index_constituents tables are dropped: no skill script writes or reads
either (see the design spec's "not ported" list), so only the bars table
survives.
"""

import os
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import duckdb

from lib.mechanics.models import Bar

DEFAULT_DB_PATH: Final = Path.home() / ".quant-plugin" / "quant.duckdb"
TABLE_BARS: Final = "bars"

_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600, owner read/write only


class DuckDBStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        os.chmod(db_path, _FILE_MODE)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_BARS} (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                provider TEXT NOT NULL,
                PRIMARY KEY (symbol, interval, ts)
            )
        """)

    def query_bars(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]:
        rows = self._conn.execute(
            f"""
            SELECT symbol, interval, ts, open, high, low, close, volume, provider
            FROM {TABLE_BARS}
            WHERE symbol = ? AND interval = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            [symbol, interval, from_, to],
        ).fetchall()
        return [
            Bar(
                symbol=r[0],
                interval=r[1],
                ts=r[2],
                open=r[3],
                high=r[4],
                low=r[5],
                close=r[6],
                volume=r[7],
                provider=r[8],
            )
            for r in rows
        ]

    def find_missing_range(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[tuple[datetime, datetime]]:
        # Detects a leading gap (requested range starts before the earliest
        # cached bar) and a trailing gap (ends after the latest cached bar).
        # Does not detect a hole in the middle of an otherwise-cached range.
        row = self._conn.execute(
            f"""
            SELECT MIN(ts), MAX(ts)
            FROM {TABLE_BARS}
            WHERE symbol = ? AND interval = ? AND ts >= ? AND ts <= ?
            """,
            [symbol, interval, from_, to],
        ).fetchone()
        assert row is not None
        earliest, latest = row
        if earliest is None:
            return [(from_, to)]

        gaps: list[tuple[datetime, datetime]] = []

        # Daily bars land at exact local-exchange midnight, compared at the
        # bar's own calendar day rather than as exact instants, since a
        # request built in UTC and a bar timestamped in the exchange's
        # local time can otherwise disagree about which calendar day an
        # instant falls on.
        if interval == "1d":
            from_in_bar_tz = from_.astimezone(earliest.tzinfo) if earliest.tzinfo else from_
            to_in_bar_tz = to.astimezone(latest.tzinfo) if latest.tzinfo else to
            if earliest.date() > from_in_bar_tz.date():
                gaps.append((from_, earliest - timedelta(microseconds=1)))
            if latest.date() < to_in_bar_tz.date():
                gaps.append((latest + timedelta(microseconds=1), to))
        else:
            if earliest > from_:
                gaps.append((from_, earliest - timedelta(microseconds=1)))
            if latest < to:
                gaps.append((latest + timedelta(microseconds=1), to))

        return gaps

    def write_bars(self, bars: list[Bar]) -> None:
        if not bars:
            return
        self._conn.executemany(
            f"""
            INSERT OR REPLACE INTO {TABLE_BARS}
                (symbol, interval, ts, open, high, low, close, volume, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    b.symbol,
                    b.interval,
                    b.ts,
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                    b.provider,
                )
                for b in bars
            ],
        )
