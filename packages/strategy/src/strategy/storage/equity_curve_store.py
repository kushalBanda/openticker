from datetime import datetime
from pathlib import Path

import duckdb
from ingest.core.constants import DEFAULT_DB_PATH

from strategy.core.constants import TABLE_EQUITY_CURVE_POINTS


class EquityCurveStore:
    """Persists a backtest run's daily mark-to-market equity curve
    (`Portfolio.equity_curve`), keyed by `run_id`. Written once, in a
    batch, after a run finishes — same pattern as `LedgerStore`.

    Distinct from the ledger: the ledger records trade fills (irregular,
    only on bars a trade actually happened), the equity curve records
    mark-to-market value on every bar. Metrics that need roughly regular
    spacing between observations (see `quant.features.statistics`) must
    use this, not fill timestamps derived from the ledger.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_EQUITY_CURVE_POINTS} (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                equity DOUBLE NOT NULL,
                PRIMARY KEY (run_id, sequence)
            )
        """)

    def write_points(self, run_id: str, equity_curve: list[tuple[datetime, float]]) -> None:
        if not equity_curve:
            return
        rows = [
            (run_id, sequence, ts, equity)
            for sequence, (ts, equity) in enumerate(equity_curve)
        ]
        self._conn.executemany(
            f"""
            INSERT OR REPLACE INTO {TABLE_EQUITY_CURVE_POINTS}
                (run_id, sequence, ts, equity)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )

    def query_points(self, run_id: str) -> list[tuple[datetime, float]]:
        rows = self._conn.execute(
            f"""
            SELECT ts, equity
            FROM {TABLE_EQUITY_CURVE_POINTS}
            WHERE run_id = ?
            ORDER BY sequence
            """,
            [run_id],
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
