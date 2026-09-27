"""A strategy's ledger: its runs across days, each with its fills, what they
paid and what they netted, and totals a review can judge it by. Pure (ADR 29
in docs/adr).

Net P&L is the legs' realized P&L less the charges their fills paid (ADR 28).
Slippage is what the fills paid beyond the prices their orders were placed
against: a cost when positive. It is already inside the realized P&L; it is
shown so a review can tell a bad rule from bad fills.

Only ended runs whose every fill paid charges count in the totals. A fill
records no charges when it came before costs were modelled, or when its
segment's charges aren't modelled (MCX): such a run would flatter the
strategy, and an open run has not finished, so both are counted but not
judged.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from openticker.core.strategies.runs import Run, RunStatus
from openticker.ports.models import EXCHANGE_TIMEZONE, Side


@dataclass(frozen=True)
class LedgerFill:
    symbol: str
    exchange: str
    side: Side
    quantity: int
    price: float
    filled_at: datetime  # tz-aware UTC
    expected_price: float | None  # None: filled before costs were modelled
    charges: float | None  # likewise

    @property
    def slippage(self) -> float | None:
        """Rupees paid beyond the expected price; negative when the fill was better."""
        if self.expected_price is None:
            return None
        moved = self.price - self.expected_price
        return round((moved if self.side is Side.BUY else -moved) * self.quantity, 2)


@dataclass(frozen=True)
class LedgerRun:
    run: Run
    fills: tuple[LedgerFill, ...]  # oldest first

    @property
    def after_costs(self) -> bool:
        """Ended, and every fill paid its charges: a run the totals judge."""
        return (
            self.run.status is RunStatus.ENDED
            and bool(self.fills)
            and all(fill.charges is not None for fill in self.fills)
        )

    @property
    def gross_pnl(self) -> float:
        return self.run.realized_pnl

    @property
    def charges(self) -> float:
        return round(sum(fill.charges or 0.0 for fill in self.fills), 2)

    @property
    def net_pnl(self) -> float:
        return round(self.gross_pnl - self.charges, 2)

    @property
    def slippage(self) -> float:
        return round(sum(fill.slippage or 0.0 for fill in self.fills), 2)


@dataclass(frozen=True)
class LedgerTotals:
    """Over the runs after costs only."""

    runs: int
    wins: int  # net P&L above zero
    losses: int  # net P&L below zero
    gross_pnl: float
    charges: float
    net_pnl: float
    slippage: float
    average_win: float | None
    average_loss: float | None  # negative
    best_run: float | None
    worst_run: float | None
    max_drawdown: float  # the deepest fall of cumulative net P&L from its high, as a positive
    stop_reasons: dict[str, int]  # how the runs ended, most common first


def ledger_totals(runs: Sequence[LedgerRun]) -> LedgerTotals:
    judged = sorted((r for r in runs if r.after_costs), key=lambda r: r.run.started_at)
    nets = [r.net_pnl for r in judged]
    wins = [net for net in nets if net > 0]
    losses = [net for net in nets if net < 0]
    reasons = Counter(str(r.run.stop_reason) if r.run.stop_reason else "unknown" for r in judged)
    return LedgerTotals(
        runs=len(judged),
        wins=len(wins),
        losses=len(losses),
        gross_pnl=round(sum(r.gross_pnl for r in judged), 2),
        charges=round(sum(r.charges for r in judged), 2),
        net_pnl=round(sum(nets), 2),
        slippage=round(sum(r.slippage for r in judged), 2),
        average_win=round(sum(wins) / len(wins), 2) if wins else None,
        average_loss=round(sum(losses) / len(losses), 2) if losses else None,
        best_run=max(nets, default=None),
        worst_run=min(nets, default=None),
        max_drawdown=_max_drawdown(nets),
        stop_reasons=dict(reasons.most_common()),
    )


def _max_drawdown(nets: Sequence[float]) -> float:
    cumulative = high = deepest = 0.0
    for net in nets:
        cumulative += net
        high = max(high, cumulative)
        deepest = max(deepest, high - cumulative)
    return round(deepest, 2)


# Days an equity curve keeps: three years of trading days.
EQUITY_DAYS = 750


@dataclass(frozen=True)
class EquityPoint:
    day: date  # exchange-local, the day the runs started
    net_pnl: float  # cumulative, after costs, at the end of that day


def equity_curve(runs: Sequence[LedgerRun], limit: int = EQUITY_DAYS) -> list[EquityPoint]:
    """Cumulative net P&L of the judged runs, day by day, oldest first: the
    latest `limit` days."""
    by_day: dict[date, float] = {}
    for entry in runs:
        if entry.after_costs:
            day = entry.run.started_at.astimezone(EXCHANGE_TIMEZONE).date()
            by_day[day] = by_day.get(day, 0.0) + entry.net_pnl
    cumulative = 0.0
    curve = []
    for day in sorted(by_day):
        cumulative += by_day[day]
        curve.append(EquityPoint(day, round(cumulative, 2)))
    return curve[-limit:]
