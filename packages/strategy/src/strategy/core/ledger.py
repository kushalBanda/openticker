from dataclasses import dataclass
from datetime import datetime


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
