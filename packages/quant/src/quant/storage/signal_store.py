from datetime import datetime
from pathlib import Path

import duckdb
from ingest.core.constants import DEFAULT_DB_PATH

from quant.core.constants import TABLE_FORECASTS, TABLE_SIGNALS
from quant.core.interfaces import Forecast, RawSignal


class SignalStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_SIGNALS} (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                name TEXT NOT NULL,
                value DOUBLE NOT NULL,
                PRIMARY KEY (symbol, interval, ts, name)
            )
        """)
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_FORECASTS} (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                name TEXT NOT NULL,
                scaled_value DOUBLE NOT NULL,
                PRIMARY KEY (symbol, interval, ts, name)
            )
        """)

    def write_signal(self, raw: RawSignal) -> None:
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO {TABLE_SIGNALS}
                (symbol, interval, ts, name, value)
            VALUES (?, ?, ?, ?, ?)
            """,
            [raw.symbol, raw.interval, raw.ts, raw.name, raw.value],
        )

    def write_forecast(self, forecast: Forecast) -> None:
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO {TABLE_FORECASTS}
                (symbol, interval, ts, name, scaled_value)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                forecast.symbol,
                forecast.interval,
                forecast.ts,
                forecast.name,
                forecast.scaled_value,
            ],
        )

    def query_signals(
        self, symbol: str, interval: str, name: str, from_: datetime, to: datetime
    ) -> list[RawSignal]:
        rows = self._conn.execute(
            f"""
            SELECT symbol, interval, ts, name, value
            FROM {TABLE_SIGNALS}
            WHERE symbol = ? AND interval = ? AND name = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            [symbol, interval, name, from_, to],
        ).fetchall()
        return [
            RawSignal(symbol=r[0], interval=r[1], ts=r[2], name=r[3], value=r[4])
            for r in rows
        ]

    def query_forecasts(
        self, symbol: str, interval: str, name: str, from_: datetime, to: datetime
    ) -> list[Forecast]:
        rows = self._conn.execute(
            f"""
            SELECT symbol, interval, ts, name, scaled_value
            FROM {TABLE_FORECASTS}
            WHERE symbol = ? AND interval = ? AND name = ? AND ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            [symbol, interval, name, from_, to],
        ).fetchall()
        return [
            Forecast(symbol=r[0], interval=r[1], ts=r[2], name=r[3], scaled_value=r[4])
            for r in rows
        ]
