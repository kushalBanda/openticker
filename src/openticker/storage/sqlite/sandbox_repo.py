"""Sandbox orders, trades, positions and funds.

A fill reads the position and funds and writes them back, and both the MCP
process and the daemon fill orders. Every fill therefore runs inside
`fill_transaction`, which takes SQLite's write lock up front (BEGIN
IMMEDIATE): a second writer waits for the first instead of both reading the
same funds and one overwriting the other (ADR 11 in docs/adr).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from openticker.core.orders.models import Order, OrderStatus, OrderType, Trade
from openticker.core.orders.sandbox import FLAT, NetPosition
from openticker.ports.models import Instrument, Product, Side
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import (
    SandboxFundsRow,
    SandboxOrderRow,
    SandboxPositionRow,
    SandboxTradeRow,
)

_FUNDS_ID = 1


@dataclass(frozen=True)
class FundsState:
    total_capital: float
    used_margin: float
    realized_pnl: float

    @property
    def available_cash(self) -> float:
        return self.total_capital - self.used_margin + self.realized_pnl


@dataclass(frozen=True)
class StoredPosition:
    exchange: str
    symbol: str
    product: Product
    position: NetPosition


@dataclass(frozen=True)
class StoredOrder:
    order_id: str
    placed_at: datetime  # tz-aware UTC
    exchange: str
    symbol: str
    side: Side
    quantity: int
    product: Product
    order_type: OrderType
    status: OrderStatus
    fill_price: float | None
    reason: str | None
    triggered_by: str
    strategy_id: str | None
    run_id: str | None
    price: float | None = None
    trigger_price: float | None = None
    triggered: bool = False
    reserved_margin: float = 0.0

    def to_order(self, instrument: Instrument) -> Order:
        return Order(
            order_id=self.order_id,
            instrument=instrument,
            side=self.side,
            quantity=self.quantity,
            product=self.product,
            order_type=self.order_type,
            status=self.status,
            fill_price=self.fill_price,
            reason=self.reason,
            triggered_by=self.triggered_by,
            placed_at=self.placed_at,
            strategy_id=self.strategy_id,
            run_id=self.run_id,
            price=self.price,
            trigger_price=self.trigger_price,
            triggered=self.triggered,
        )


@dataclass(frozen=True)
class StoredTrade:
    order_id: str
    filled_at: datetime  # tz-aware UTC
    exchange: str
    symbol: str
    side: Side
    quantity: int
    price: float
    product: Product
    triggered_by: str
    strategy_id: str | None
    run_id: str | None

    def to_trade(self, instrument: Instrument) -> Trade:
        return Trade(
            order_id=self.order_id,
            instrument=instrument,
            side=self.side,
            quantity=self.quantity,
            price=self.price,
            product=self.product,
            filled_at=self.filled_at,
            triggered_by=self.triggered_by,
            strategy_id=self.strategy_id,
            run_id=self.run_id,
        )


@contextmanager
def fill_transaction() -> Iterator[Session]:
    """A session holding SQLite's write lock from its first statement until
    commit. Commits on normal exit, rolls back on an exception."""
    with get_engine().connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=connection) as session:
            yield session
            session.flush()
        connection.commit()


def load_funds(session: Session, starting_capital: float) -> FundsState:
    """Funds, created with `starting_capital` the first time they are read."""
    row = session.get(SandboxFundsRow, _FUNDS_ID)
    if row is None:
        row = SandboxFundsRow(
            id=_FUNDS_ID, total_capital=starting_capital, used_margin=0.0, realized_pnl=0.0
        )
        session.add(row)
    return FundsState(row.total_capital, row.used_margin, row.realized_pnl)


def save_funds(session: Session, funds: FundsState) -> None:
    session.merge(
        SandboxFundsRow(
            id=_FUNDS_ID,
            total_capital=funds.total_capital,
            used_margin=funds.used_margin,
            realized_pnl=funds.realized_pnl,
        )
    )


def load_position(session: Session, exchange: str, symbol: str, product: Product) -> NetPosition:
    row = session.get(SandboxPositionRow, (exchange, symbol, product.value))
    if row is None:
        return FLAT
    return NetPosition(row.quantity, row.average_price, row.margin_blocked, row.realized_pnl)


def save_position(
    session: Session, exchange: str, symbol: str, product: Product, position: NetPosition
) -> None:
    session.merge(
        SandboxPositionRow(
            exchange=exchange,
            symbol=symbol,
            product=product.value,
            quantity=position.quantity,
            average_price=position.average_price,
            margin_blocked=position.margin_blocked,
            realized_pnl=position.realized_pnl,
        )
    )


def record_order(session: Session, order: StoredOrder) -> None:
    session.add(
        SandboxOrderRow(
            order_id=order.order_id,
            placed_at=_naive_utc(order.placed_at),
            exchange=order.exchange,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            product=order.product.value,
            order_type=order.order_type.value,
            status=order.status.value,
            fill_price=order.fill_price,
            reason=order.reason,
            triggered_by=order.triggered_by,
            strategy_id=order.strategy_id,
            run_id=order.run_id,
            price=order.price,
            trigger_price=order.trigger_price,
            triggered=order.triggered,
            reserved_margin=order.reserved_margin,
            updated_at=None,
        )
    )
    if order.status is OrderStatus.FILLED and order.fill_price is not None:
        _add_trade(session, order, order.fill_price, order.placed_at)


def load_order(session: Session, order_id: str) -> StoredOrder | None:
    row = session.get(SandboxOrderRow, order_id)
    return _stored(row) if row is not None else None


def update_order(session: Session, order: StoredOrder, now: datetime) -> None:
    """Writes a resting order's new state; a fill also records its trade."""
    row = session.get(SandboxOrderRow, order.order_id)
    if row is None:
        raise LookupError(f"no sandbox order {order.order_id}")
    row.status = order.status.value
    row.fill_price = order.fill_price
    row.reason = order.reason
    row.triggered = order.triggered
    row.reserved_margin = order.reserved_margin
    row.updated_at = _naive_utc(now)
    if order.status is OrderStatus.FILLED and order.fill_price is not None:
        _add_trade(session, order, order.fill_price, now)


def _add_trade(session: Session, order: StoredOrder, price: float, filled_at: datetime) -> None:
    session.add(
        SandboxTradeRow(
            order_id=order.order_id,
            filled_at=_naive_utc(filled_at),
            exchange=order.exchange,
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            price=price,
            product=order.product.value,
            strategy_id=order.strategy_id,
            run_id=order.run_id,
        )
    )


def read_funds(starting_capital: float) -> FundsState:
    with fill_transaction() as session:  # creates the row on first read
        return load_funds(session, starting_capital)


def list_positions() -> list[StoredPosition]:
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(SandboxPositionRow).order_by(
                SandboxPositionRow.exchange, SandboxPositionRow.symbol
            )
        ).all()
    return [
        StoredPosition(
            row.exchange,
            row.symbol,
            Product(row.product),
            NetPosition(row.quantity, row.average_price, row.margin_blocked, row.realized_pnl),
        )
        for row in rows
    ]


def list_orders(limit: int) -> list[StoredOrder]:
    """Most recent first."""
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(SandboxOrderRow)
            .order_by(SandboxOrderRow.placed_at.desc(), SandboxOrderRow.order_id.desc())
            .limit(limit)
        ).all()
    return [_stored(row) for row in rows]


def list_trades(since: datetime, limit: int) -> list[StoredTrade]:
    """Fills at or after `since`, newest first, each with who placed its order."""
    with Session(get_engine()) as session:
        rows = session.execute(
            select(SandboxTradeRow, SandboxOrderRow.triggered_by)
            .join(SandboxOrderRow, SandboxOrderRow.order_id == SandboxTradeRow.order_id)
            .where(SandboxTradeRow.filled_at >= _naive_utc(since))
            .order_by(SandboxTradeRow.filled_at.desc(), SandboxTradeRow.id.desc())
            .limit(limit)
        ).all()
    return [
        StoredTrade(
            order_id=trade.order_id,
            filled_at=trade.filled_at.replace(tzinfo=UTC),
            exchange=trade.exchange,
            symbol=trade.symbol,
            side=Side(trade.side),
            quantity=trade.quantity,
            price=trade.price,
            product=Product(trade.product),
            triggered_by=triggered_by,
            strategy_id=trade.strategy_id,
            run_id=trade.run_id,
        )
        for trade, triggered_by in rows
    ]


def find_order(order_id: str) -> StoredOrder | None:
    with Session(get_engine()) as session:
        row = session.get(SandboxOrderRow, order_id)
        return _stored(row) if row is not None else None


def list_run_orders(run_id: str) -> list[StoredOrder]:
    """Every order tagged with the strategy run, in the order they were placed."""
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(SandboxOrderRow)
            .where(SandboxOrderRow.run_id == run_id)
            .order_by(literal_column("rowid"))
        ).all()
    return [_stored(row) for row in rows]


def list_pending_orders() -> list[StoredOrder]:
    """Oldest first, so earlier orders fill first on the same price."""
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(SandboxOrderRow)
            .where(SandboxOrderRow.status == OrderStatus.PENDING.value)
            .order_by(SandboxOrderRow.placed_at, SandboxOrderRow.order_id)
        ).all()
    return [_stored(row) for row in rows]


def _stored(row: SandboxOrderRow) -> StoredOrder:
    return StoredOrder(
        order_id=row.order_id,
        placed_at=row.placed_at.replace(tzinfo=UTC),
        exchange=row.exchange,
        symbol=row.symbol,
        side=Side(row.side),
        quantity=row.quantity,
        product=Product(row.product),
        order_type=OrderType(row.order_type),
        status=OrderStatus(row.status),
        fill_price=row.fill_price,
        reason=row.reason,
        triggered_by=row.triggered_by,
        strategy_id=row.strategy_id,
        run_id=row.run_id,
        price=row.price,
        trigger_price=row.trigger_price,
        triggered=bool(row.triggered),
        reserved_margin=row.reserved_margin or 0.0,
    )


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)
