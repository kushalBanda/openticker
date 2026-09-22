from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError
from openticker.storage.sqlite.engine import get_engine
from openticker.use_cases.api_keys import (
    InvalidApiKeyNameError,
    authenticate,
    create_api_key,
    get_api_keys,
    revoke,
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
