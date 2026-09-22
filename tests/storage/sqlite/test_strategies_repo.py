from datetime import timedelta

import pytest

from openticker.storage.sqlite.strategies_repo import (
    DuplicateStrategyNameError,
    delete_strategy,
    find_strategy,
    insert_strategy,
    list_strategies,
    update_strategy,
)
from tests.fixtures.strategies import EVERYTHING, NOW, STRADDLE


def test_definition_round_trips_every_field() -> None:
    stored = insert_strategy("everything", EVERYTHING, NOW)

    found = find_strategy(stored.id)

    assert found is not None
    assert found.spec == EVERYTHING
    assert (found.name, found.mode, found.locked, found.created_at) == (
        "everything",
        "sandbox",
        False,
        NOW,
    )


def test_names_are_unique_until_deleted() -> None:
    first = insert_strategy("straddle", STRADDLE, NOW)

    with pytest.raises(DuplicateStrategyNameError, match="straddle"):
        insert_strategy("straddle", STRADDLE, NOW)
    assert delete_strategy(first.id, NOW) is True
    second = insert_strategy("straddle", STRADDLE, NOW)

    assert second.id != first.id
    assert find_strategy(first.id) is None
    assert [stored.id for stored in list_strategies()] == [second.id]


def test_update_replaces_definition_and_refuses_a_taken_name() -> None:
    straddle = insert_strategy("straddle", STRADDLE, NOW)
    insert_strategy("other", STRADDLE, NOW)
    later = NOW + timedelta(minutes=5)

    updated = update_strategy(straddle.id, "straddle", EVERYTHING, later)
    with pytest.raises(DuplicateStrategyNameError):
        update_strategy(straddle.id, "other", STRADDLE, later)

    assert updated is not None and updated.spec == EVERYTHING and updated.updated_at == later
    assert update_strategy("stg_missing", "x", STRADDLE, NOW) is None
    assert delete_strategy("stg_missing", NOW) is False
