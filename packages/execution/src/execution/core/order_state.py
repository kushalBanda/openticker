from strategy.core.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_REJECTED,
)

from execution.core.exceptions import InvalidTransitionError

# Terminal states have no outgoing transitions. PARTIALLY_FILLED allows a
# self-loop (another partial fill) as well as progressing to FILLED or
# being CANCELLED mid-fill.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ORDER_STATUS_PENDING: frozenset(
        {ORDER_STATUS_OPEN, ORDER_STATUS_REJECTED, ORDER_STATUS_CANCELLED}
    ),
    ORDER_STATUS_OPEN: frozenset(
        {
            ORDER_STATUS_PARTIALLY_FILLED,
            ORDER_STATUS_FILLED,
            ORDER_STATUS_CANCELLED,
            ORDER_STATUS_REJECTED,
        }
    ),
    ORDER_STATUS_PARTIALLY_FILLED: frozenset(
        {ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_FILLED, ORDER_STATUS_CANCELLED}
    ),
    ORDER_STATUS_FILLED: frozenset(),
    ORDER_STATUS_CANCELLED: frozenset(),
    ORDER_STATUS_REJECTED: frozenset(),
}


def transition(current: str, target: str) -> str:
    allowed = _ALLOWED_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTransitionError(f"unknown order status {current!r}")
    if target not in allowed:
        raise InvalidTransitionError(f"cannot transition order from {current!r} to {target!r}")
    return target
