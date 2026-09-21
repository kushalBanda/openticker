from datetime import UTC, datetime
from pathlib import Path

from openticker.ports.models import Credentials
from openticker.storage.sqlite import credentials_repo
from openticker.storage.sqlite.engine import get_engine


def test_save_and_get_credentials_round_trips() -> None:
    original = Credentials(
        broker="zerodha",
        access_token="super-secret-token",
        refresh_token="super-secret-refresh",
        expires_at=datetime(2026, 12, 31, tzinfo=UTC),
    )

    credentials_repo.save_credentials(original)
    loaded = credentials_repo.get_credentials("zerodha")

    assert loaded == original


def test_get_credentials_returns_none_when_absent() -> None:
    assert credentials_repo.get_credentials("nonexistent") is None


def test_reconnecting_a_broker_overwrites_not_duplicates() -> None:
    credentials_repo.save_credentials(
        Credentials(broker="zerodha", access_token="first-token", refresh_token=None, expires_at=None)
    )
    credentials_repo.save_credentials(
        Credentials(broker="zerodha", access_token="second-token", refresh_token=None, expires_at=None)
    )

    loaded = credentials_repo.get_credentials("zerodha")

    assert loaded is not None
    assert loaded.access_token == "second-token"


def test_access_token_is_never_stored_as_plaintext_on_disk() -> None:
    credentials_repo.save_credentials(
        Credentials(
            broker="zerodha",
            access_token="super-secret-token",
            refresh_token=None,
            expires_at=None,
        )
    )

    db_path = get_engine().url.database
    assert db_path is not None
    raw_bytes = Path(db_path).read_bytes()
    assert b"super-secret-token" not in raw_bytes
