from pathlib import Path

import duckdb
from ingest.core.constants import DEFAULT_DB_PATH

from strategy.core.constants import TABLE_LEDGER_ENTRIES
from strategy.core.ledger import LedgerEntry


class LedgerStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_LEDGER_ENTRIES} (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                fill_price DOUBLE NOT NULL,
                fill_ts TIMESTAMPTZ NOT NULL,
                commission DOUBLE NOT NULL,
                cost_basis_before DOUBLE NOT NULL,
                realized_pnl DOUBLE NOT NULL,
                cash_after DOUBLE NOT NULL,
                position_after INTEGER NOT NULL,
                PRIMARY KEY (run_id, sequence)
            )
        """)

    def write_entries(self, run_id: str, entries: list[LedgerEntry]) -> None:
        rows = [
            (
                run_id,
                sequence,
                entry.symbol,
                entry.side,
                entry.quantity,
                entry.fill_price,
                entry.fill_ts,
                entry.commission,
                entry.cost_basis_before,
                entry.realized_pnl,
                entry.cash_after,
                entry.position_after,
            )
            for sequence, entry in enumerate(entries)
        ]
        self._conn.executemany(
            f"""
            INSERT OR REPLACE INTO {TABLE_LEDGER_ENTRIES}
                (run_id, sequence, symbol, side, quantity, fill_price, fill_ts,
                 commission, cost_basis_before, realized_pnl, cash_after, position_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def query_entries(self, run_id: str) -> list[LedgerEntry]:
        rows = self._conn.execute(
            f"""
            SELECT symbol, side, quantity, fill_price, fill_ts, commission,
                   cost_basis_before, realized_pnl, cash_after, position_after
            FROM {TABLE_LEDGER_ENTRIES}
            WHERE run_id = ?
            ORDER BY sequence
            """,
            [run_id],
        ).fetchall()
        return [
            LedgerEntry(
                symbol=r[0],
                side=r[1],
                quantity=r[2],
                fill_price=r[3],
                fill_ts=r[4],
                commission=r[5],
                cost_basis_before=r[6],
                realized_pnl=r[7],
                cash_after=r[8],
                position_after=r[9],
            )
            for r in rows
        ]
