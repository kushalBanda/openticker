from dataclasses import dataclass

from agents.advisors.core.exceptions import InvalidProposalError
from agents.advisors.pairs_trading.constants import (
    BUFFER_MAX,
    BUFFER_MIN,
    CAPITAL_RECONCILE_TOLERANCE,
    ENTRY_Z_MAX,
    ENTRY_Z_MIN,
    FORMATION_MONTHS_MAX,
    FORMATION_MONTHS_MIN,
    TRADING_MONTHS_MAX,
    TRADING_MONTHS_MIN,
)


@dataclass(frozen=True)
class CandidateStats:
    """One pair in the Advisor's candidate window.

    `win_rate`/`realized_pnl`/`trade_count` are `None` for a pair with no
    prior trade history — CONTEXT.md's cold-start rule: absent, not a null
    placeholder, so the prompt can omit the key entirely rather than imply
    "0% win rate" for a pair that has simply never traded.
    """

    symbol_a: str
    symbol_b: str
    ssd: float
    spread_mean: float
    spread_std: float
    realized_vol: float
    correlation: float
    win_rate: float | None = None
    realized_pnl: float | None = None
    trade_count: int | None = None


@dataclass(frozen=True)
class SelectedPairWeight:
    """A pair the Advisor chose to trade this cycle, and its capital weight.

    `weight` is a fraction of `1 - buffer`, never a share quantity — code
    (not the Advisor) performs the deterministic price-division that turns
    a weight into a share count.
    """

    symbol_a: str
    symbol_b: str
    weight: float


@dataclass(frozen=True)
class PairsTradingProposal:
    """The Advisor's validated output for one reformation cycle."""

    entry_z: float
    formation_months: int
    trading_months: int
    buffer: float
    selected: tuple[SelectedPairWeight, ...]


def _check_bounds(name: str, value: float, low: float, high: float) -> None:
    if not (low <= value <= high):
        raise InvalidProposalError(f"{name} {value} outside [{low}, {high}]")


def validate_proposal(
    proposal: PairsTradingProposal, candidate_symbols: set[tuple[str, str]]
) -> None:
    """Raises `InvalidProposalError` on any bounds violation, unknown/duplicate
    pair, or a weight+buffer sum that doesn't reconcile to 1.0 within
    `CAPITAL_RECONCILE_TOLERANCE`.
    """
    _check_bounds("entry_z", proposal.entry_z, ENTRY_Z_MIN, ENTRY_Z_MAX)
    _check_bounds(
        "formation_months", proposal.formation_months, FORMATION_MONTHS_MIN, FORMATION_MONTHS_MAX
    )
    _check_bounds(
        "trading_months", proposal.trading_months, TRADING_MONTHS_MIN, TRADING_MONTHS_MAX
    )
    _check_bounds("buffer", proposal.buffer, BUFFER_MIN, BUFFER_MAX)

    if not proposal.selected:
        raise InvalidProposalError("selected pairs must not be empty")

    seen: set[tuple[str, str]] = set()
    for selection in proposal.selected:
        key = (selection.symbol_a, selection.symbol_b)
        if key not in candidate_symbols:
            raise InvalidProposalError(f"pair {key} is not in the candidate window")
        if key in seen:
            raise InvalidProposalError(f"pair {key} selected more than once")
        seen.add(key)
        if selection.weight <= 0:
            raise InvalidProposalError(f"weight for {key} must be positive, got {selection.weight}")

    total_weight = sum(selection.weight for selection in proposal.selected)
    expected_total = 1.0 - proposal.buffer
    if abs(total_weight - expected_total) > CAPITAL_RECONCILE_TOLERANCE:
        raise InvalidProposalError(
            f"selected weights sum to {total_weight:.4f}, expected {expected_total:.4f} "
            f"(1 - buffer={proposal.buffer})"
        )
