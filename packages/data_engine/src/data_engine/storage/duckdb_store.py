from datetime import datetime
from pathlib import Path

import duckdb

from data_engine.core.constants import DEFAULT_DB_PATH, TABLE_BARS, TABLE_TICKS
from data_engine.core.models import Bar, Tick


class DuckDBStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_BARS} (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                provider TEXT NOT NULL,
                PRIMARY KEY (symbol, interval, ts)
            )
        """)
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_TICKS} (
                symbol TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                price DOUBLE NOT NULL,
                volume BIGINT NOT NULL,
                provider TEXT NOT NULL
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
        existing = self.query_bars(symbol, interval, from_, to)
        if not existing:
            return [(from_, to)]
        if existing[0].ts <= from_ and existing[-1].ts >= to:
            return []
        return [(from_, to)]

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

    def write_tick(self, tick: Tick) -> None:
        self._conn.execute(
            f"""
            INSERT INTO {TABLE_TICKS} (symbol, ts, price, volume, provider)
            VALUES (?, ?, ?, ?, ?)
            """,
            [tick.symbol, tick.ts, tick.price, tick.volume, tick.provider],
        )
