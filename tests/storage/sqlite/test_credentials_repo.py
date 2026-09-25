from datetime import UTC, datetime
from pathlib import Path

from openticker.ports.models import Credentials
from openticker.storage.sqlite import credentials_repo
from openticker.storage.sqlite.engine import get_data_dir, get_engine


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
        Credentials(
            broker="zerodha", access_token="first-token", refresh_token=None, expires_at=None
        )
    )
    credentials_repo.save_credentials(
        Credentials(
            broker="zerodha", access_token="second-token", refresh_token=None, expires_at=None
        )
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


def test_threads_asking_for_the_key_at_once_on_a_new_home_all_get_the_same_whole_key() -> None:
    import threading

    from openticker.storage.sqlite.credentials_repo import _get_or_create_key

    keys: list[bytes] = []
    start = threading.Barrier(16)

    def ask() -> None:
        start.wait()
        keys.append(_get_or_create_key())

    threads = [threading.Thread(target=ask) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(keys)) == 1 and len(keys[0]) == 44
    assert oct((get_data_dir() / "secret.key").stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in get_data_dir().iterdir() if p.name.startswith(".secret")] == []
