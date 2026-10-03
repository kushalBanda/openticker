from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError
from openticker.storage.sqlite.engine import get_engine
from openticker.use_cases.api_keys import (
    InvalidApiKeyNameError,
    ManagedApiKeyError,
    UnknownApiKeyError,
    authenticate,
    create_api_key,
    create_script_key,
    get_api_keys,
    revoke,
    revoke_user_key,
)

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


def test_a_created_key_authenticates_and_is_never_stored() -> None:
    stored, key = create_api_key("laptop", NOW)

    assert key.startswith("otk_") and len(key) > 40
    assert authenticate(key) == stored
    assert authenticate(key + "x") is None
    with get_engine().connect() as connection:
        rows = connection.execute(text("SELECT * FROM api_keys")).all()
    assert not any(key in str(value) for row in rows for value in row)
    assert key.startswith(stored.prefix) and len(stored.prefix) < 12


def test_each_key_is_different() -> None:
    _, first = create_api_key("one", NOW)
    _, second = create_api_key("two", NOW)

    assert first != second


def test_a_revoked_key_stops_working_and_its_name_is_not_reused() -> None:
    _, key = create_api_key("laptop", NOW)

    assert revoke("laptop", NOW)
    assert authenticate(key) is None
    assert not revoke("laptop", NOW)
    assert [stored.revoked_at for stored in get_api_keys()] == [NOW]
    with pytest.raises(DuplicateApiKeyNameError, match="laptop"):
        create_api_key("laptop", NOW)


@pytest.mark.parametrize("name", ["", "Laptop", "my key", "x" * 41, "-dash"])
def test_key_names_are_short_plain_labels(name: str) -> None:
    with pytest.raises(InvalidApiKeyNameError):
        create_api_key(name, NOW)


def test_script_keys_are_scoped_named_by_their_run_and_their_names_reserved() -> None:
    from openticker.use_cases.api_keys import create_script_key, revoke_script_keys

    with pytest.raises(InvalidApiKeyNameError, match="kept for hosted scripts"):
        create_api_key("script-mine", NOW)
    _, laptop = create_api_key("laptop", NOW)
    first = create_script_key("scr_a", "srn_1", NOW)
    second = create_script_key("scr_a", "srn_2", NOW)
    stored = authenticate(first)
    assert stored is not None
    assert (stored.name, stored.scope) == ("script-srn_1", "script:scr_a")

    assert revoke_script_keys({"srn_2"}, NOW) == 1

    assert authenticate(first) is None
    assert authenticate(second) is not None
    assert authenticate(laptop) is not None  # never a script's


def test_review_keys_read_one_strategy_and_are_all_revoked_together() -> None:
    from openticker.use_cases.api_keys import create_review_key, revoke_agent_keys

    with pytest.raises(InvalidApiKeyNameError, match="kept for agent jobs"):
        create_api_key("agent-mine", NOW)
    _, laptop = create_api_key("laptop", NOW)
    review = create_review_key("stg_a", "job_1", NOW)
    stored = authenticate(review)
    assert stored is not None
    assert (stored.name, stored.scope) == ("agent-job_1", "review:stg_a")

    assert revoke_agent_keys(NOW) == 1

    assert authenticate(review) is None
    assert authenticate(laptop) is not None


def test_the_user_revokes_their_own_keys_only() -> None:
    _, key = create_api_key("laptop", NOW)
    create_script_key("scr_1", "run_1", NOW)

    revoke_user_key("laptop", NOW)

    assert authenticate(key) is None
    with pytest.raises(UnknownApiKeyError):
        revoke_user_key("laptop", NOW)
    with pytest.raises(ManagedApiKeyError, match="stop the script"):
        revoke_user_key("script-run_1", NOW)
