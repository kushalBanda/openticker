"""A strategy's ledger (ADR 29 in docs/adr): the one read a review needs. The
newest runs in detail, and totals over every run it has had."""

from collections import defaultdict
from dataclasses import dataclass

from openticker.core.strategies.ledger import (
    EquityPoint,
    LedgerFill,
    LedgerRun,
    LedgerTotals,
    equity_curve,
    ledger_totals,
)
from openticker.core.strategies.runs import RunStatus
from openticker.storage.sqlite import runs_repo, sandbox_repo, strategies_repo
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.use_cases.strategies.define import UnknownStrategyError

# Runs shown in detail per answer, which keeps it bounded (ADR 8 in docs/adr).
MAX_LEDGER_RUNS = 50
# Runs the totals read: years of daily runs.
LEDGER_HISTORY = 5_000


@dataclass(frozen=True)
class StrategyLedger:
    strategy: StoredStrategy
    runs: list[LedgerRun]  # newest first, at most the limit asked for
    total_runs: int  # every run it has had
    uncharged: int  # ended runs with a fill that recorded no charges
    open_runs: int  # not ended yet
    totals: LedgerTotals  # over the runs after costs
    equity: list[EquityPoint]  # cumulative net after costs, day by day


def get_strategy_ledger(strategy_id: str, limit: int) -> StrategyLedger:
    stored = strategies_repo.find_strategy(strategy_id)
    if stored is None:
        raise UnknownStrategyError(
            f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
        )
    runs = ledger_runs(strategy_id)
    ended = [r for r in runs if r.run.status is RunStatus.ENDED]
    return StrategyLedger(
        strategy=stored,
        runs=runs[: min(limit, MAX_LEDGER_RUNS)],
        total_runs=len(runs),
        uncharged=sum(1 for r in ended if r.fills and not r.after_costs),
        open_runs=len(runs) - len(ended),
        totals=ledger_totals(runs),
        equity=equity_curve(runs),
    )


def ledger_runs(strategy_id: str) -> list[LedgerRun]:
    """Every run it has had, newest first, each with its fills."""
    fills: dict[str, list[LedgerFill]] = defaultdict(list)
    for trade in sandbox_repo.list_strategy_trades(strategy_id):
        if trade.run_id is not None:
            fills[trade.run_id].append(
                LedgerFill(
                    symbol=trade.symbol,
                    exchange=trade.exchange,
                    side=trade.side,
                    quantity=trade.quantity,
                    price=trade.price,
                    filled_at=trade.filled_at,
                    expected_price=trade.expected_price,
                    charges=trade.charges,
                )
            )
    return [
        LedgerRun(run, tuple(fills.get(run.id, ())))
        for run in runs_repo.list_runs(strategy_id, LEDGER_HISTORY)
    ]
