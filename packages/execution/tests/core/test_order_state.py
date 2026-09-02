import pytest
from execution.core.exceptions import InvalidTransitionError
from execution.core.order_state import transition
from strategy.core.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_PENDING,
)


def test_valid_transition_pending_to_open_succeeds() -> None:
    assert transition(ORDER_STATUS_PENDING, ORDER_STATUS_OPEN) == ORDER_STATUS_OPEN


def test_valid_transition_open_to_partially_filled_to_filled_succeeds() -> None:
    state = transition(ORDER_STATUS_OPEN, ORDER_STATUS_PARTIALLY_FILLED)
    state = transition(state, ORDER_STATUS_FILLED)
    assert state == ORDER_STATUS_FILLED


def test_invalid_transition_filled_to_open_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(ORDER_STATUS_FILLED, ORDER_STATUS_OPEN)


def test_invalid_transition_cancelled_to_filled_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(ORDER_STATUS_CANCELLED, ORDER_STATUS_FILLED)


def test_unknown_current_status_raises() -> None:
    with pytest.raises(InvalidTransitionError):
        transition("not_a_real_status", ORDER_STATUS_OPEN)
