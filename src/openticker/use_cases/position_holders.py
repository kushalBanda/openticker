"""Who holds each open position (ADR 35 in docs/adr): the running
strategies whose open legs make it up, and the rest, labelled by who placed
it.

The sandbox keeps one net position per contract and product, so a strategy
and you can share one. Each strategy's open legs are counted on the
contract; what is left of the net quantity is the rest. When the legs don't
fit inside the position (two strategies on opposite sides, or a leg the
position no longer covers), the position is marked shared and has no rest:
closing it closes whatever the strategies still think they hold.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from openticker.core.pnl import Source, source_of
from openticker.ports.models import Position, Product, Side
from openticker.storage.sqlite import runs_repo, sandbox_repo, strategies_repo

PositionKey = tuple[str, str, Product]  # exchange, symbol, product


@dataclass(frozen=True)
class Holder:
    strategy_id: str | None  # None: the rest, outside strategies
    name: str | None  # the strategy's name
    source: Source  # for the rest, who placed it
    quantity: int  # net and signed, as the position's
    leg_ids: tuple[str, ...] = ()  # the strategy's open legs on the contract


@dataclass(frozen=True)
class Holding:
    holders: tuple[Holder, ...]
    shared: bool


def key_of(position: Position) -> PositionKey:
    return position.instrument.exchange.value, position.instrument.symbol, position.product


def holders(positions: Sequence[Position]) -> dict[PositionKey, Holding]:
    """For each open position in `positions`."""
    legs: dict[PositionKey, dict[str, tuple[int, list[str]]]] = {}
    for run in runs_repo.active_runs():
        for leg in run.legs:
            if not leg.is_open:
                continue
            key = (leg.exchange.value, leg.symbol, run.product)
            quantity, leg_ids = legs.setdefault(key, {}).get(run.strategy_id, (0, []))
            signed = leg.quantity if leg.side is Side.BUY else -leg.quantity
            legs[key][run.strategy_id] = (quantity + signed, [*leg_ids, leg.leg_id])

    names: dict[str, str | None] = {}
    held: dict[PositionKey, Holding] = {}
    for position in positions:
        if position.quantity == 0:
            continue
        key = key_of(position)
        strategies = [
            Holder(
                strategy_id,
                _name(names, strategy_id),
                Source.STRATEGY,
                quantity,
                tuple(leg_ids),
            )
            for strategy_id, (quantity, leg_ids) in legs.get(key, {}).items()
            if quantity
        ]
        rest = position.quantity - sum(holder.quantity for holder in strategies)
        fits = all(_same_side(h.quantity, position.quantity) for h in strategies) and (
            rest == 0 or _same_side(rest, position.quantity)
        )
        if not fits:
            held[key] = Holding(tuple(strategies), shared=True)
            continue
        if rest:
            side = Side.BUY if position.quantity > 0 else Side.SELL
            placer = sandbox_repo.last_placer(key[0], key[1], key[2], side)
            strategies.append(Holder(None, None, source_of(placer), rest))
        held[key] = Holding(tuple(strategies), shared=False)
    return held


def _same_side(a: int, b: int) -> bool:
    return (a > 0) == (b > 0)


def _name(names: dict[str, str | None], strategy_id: str) -> str | None:
    """None when the strategy was deleted."""
    if strategy_id not in names:
        stored = strategies_repo.find_strategy(strategy_id)
        names[strategy_id] = stored.name if stored is not None else None
    return names[strategy_id]
