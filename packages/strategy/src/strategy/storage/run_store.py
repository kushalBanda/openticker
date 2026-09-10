import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
from ingest.core.constants import DEFAULT_DB_PATH

from strategy.core.constants import TABLE_RUNS


@dataclass(frozen=True)
class RunMetadata:
    run_id: str
    created_at: datetime
    strategy: str
    params: dict[str, float | int]
    symbols: list[str]
    interval: str
    starting_cash: float


class RunStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_RUNS} (
                run_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                strategy TEXT NOT NULL,
                params_json TEXT NOT NULL,
                symbols_json TEXT NOT NULL,
                interval TEXT NOT NULL,
                starting_cash DOUBLE NOT NULL
            )
        """)

    def write_run(self, run: RunMetadata) -> None:
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO {TABLE_RUNS}
                (run_id, created_at, strategy, params_json, symbols_json, interval, starting_cash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.run_id,
                run.created_at,
                run.strategy,
                json.dumps(run.params),
                json.dumps(run.symbols),
                run.interval,
                run.starting_cash,
            ],
        )

    def get_run(self, run_id: str) -> RunMetadata | None:
        row = self._conn.execute(
            f"""
            SELECT run_id, created_at, strategy, params_json, symbols_json, interval, starting_cash
            FROM {TABLE_RUNS}
            WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()
        if row is None:
            return None
        return RunMetadata(
            run_id=row[0],
            created_at=row[1],
            strategy=row[2],
            params=json.loads(row[3]),
            symbols=json.loads(row[4]),
            interval=row[5],
            starting_cash=row[6],
        )

    def get_most_recent_run(self) -> RunMetadata | None:
        row = self._conn.execute(
            f"""
            SELECT run_id, created_at, strategy, params_json, symbols_json, interval, starting_cash
            FROM {TABLE_RUNS}
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return RunMetadata(
            run_id=row[0],
            created_at=row[1],
            strategy=row[2],
            params=json.loads(row[3]),
            symbols=json.loads(row[4]),
            interval=row[5],
            starting_cash=row[6],
        )
