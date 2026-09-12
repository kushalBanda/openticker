from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
from ingest.core.constants import DEFAULT_DB_PATH

from strategy.core.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_REJECTED,
    TABLE_ORDERS,
)
from strategy.core.models import Order, OrderState

# Reaching a terminal status ends an order's lifecycle - it never
# transitions again, so a reconciliation-on-restart pass only needs to
# look at orders NOT in one of these.
_TERMINAL_STATUSES = (ORDER_STATUS_FILLED, ORDER_STATUS_CANCELLED, ORDER_STATUS_REJECTED)


class OrderStore:
    """Write-ahead persistence for PaperBroker/LiveBroker order state.

    BacktestBroker never needs this - its orders live and die within one
    in-memory run. PaperBroker/LiveBroker persist every status transition
    here BEFORE calling a real broker's API, so a crash mid-submission (or
    the process restarting for any other reason) can reconcile against the
    broker's own order book instead of trusting lost in-memory state - see
    docs/designs/trading-bot-first-pivot.md's "Order Lifecycle Design".
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_ORDERS} (
                order_id TEXT PRIMARY KEY,
                broker_order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                order_type TEXT NOT NULL,
                placed_at_ts TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL,
                updated_ts TIMESTAMPTZ NOT NULL
            )
        """)

    def write_state(self, state: OrderState, updated_ts: datetime) -> None:
        order = state.order
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO {TABLE_ORDERS}
                (order_id, broker_order_id, symbol, side, quantity, order_type,
                 placed_at_ts, status, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                order.order_id,
                state.broker_order_id,
                order.symbol,
                order.side,
                order.quantity,
                order.order_type,
                order.placed_at_ts,
                state.status,
                updated_ts,
            ],
        )

    def get_state(self, order_id: str) -> OrderState | None:
        row = self._conn.execute(
            f"""
            SELECT order_id, broker_order_id, symbol, side, quantity, order_type,
                   placed_at_ts, status
            FROM {TABLE_ORDERS}
            WHERE order_id = ?
            """,
            [order_id],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def list_non_terminal(self) -> list[OrderState]:
        placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
        rows = self._conn.execute(
            f"""
            SELECT order_id, broker_order_id, symbol, side, quantity, order_type,
                   placed_at_ts, status
            FROM {TABLE_ORDERS}
            WHERE status NOT IN ({placeholders})
            ORDER BY placed_at_ts
            """,
            list(_TERMINAL_STATUSES),
        ).fetchall()
        return [self._row_to_state(row) for row in rows]

    @staticmethod
    def _row_to_state(row: tuple[Any, ...]) -> OrderState:
        (
            order_id,
            broker_order_id,
            symbol,
            side,
            quantity,
            order_type,
            placed_at_ts,
            status,
        ) = row
        return OrderState(
            order=Order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                placed_at_ts=placed_at_ts,
                order_id=order_id,
            ),
            status=status,
            broker_order_id=broker_order_id,
        )
