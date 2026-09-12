"""Order, Fill, and ledger records for the backtest loop.

Ported from strategy.core.{models,ledger}. OrderState.broker_order_id is
dropped: it only ever meant anything for a live/paper broker, which is
not ported (see the design spec's "not ported" list).
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from lib.math.constants import ORDER_STATUS_PENDING


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    quantity: int
    order_type: str
    placed_at_ts: datetime
    order_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class Fill:
    order: Order
    fill_price: float
    fill_ts: datetime
    commission: float


@dataclass(frozen=True)
class OrderState:
    order: Order
    status: str = ORDER_STATUS_PENDING


@dataclass(frozen=True)
class LedgerEntry:
    symbol: str
    side: str
    quantity: int
    fill_price: float
    fill_ts: datetime
    commission: float
    cost_basis_before: float
    realized_pnl: float
    cash_after: float
    position_after: int


class TradeLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def record(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)

    @property
    def entries(self) -> list[LedgerEntry]:
        return list(self._entries)
