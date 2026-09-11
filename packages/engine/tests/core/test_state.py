from pathlib import Path

import pytest
from engine.core import state


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "credentials.duckdb"
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "CREDENTIALS_DB", db_path)
    return db_path


def test_save_and_load_round_trip(isolated_state: Path) -> None:
    state.save_credentials("kite", {"api_key": "k1", "access_token": "t1"})
    assert state.load_credentials("kite") == {"api_key": "k1", "access_token": "t1"}


def test_load_credentials_returns_none_when_never_connected(isolated_state: Path) -> None:
    assert state.load_credentials("groww") is None


def test_load_most_recent_returns_latest_connected(isolated_state: Path) -> None:
    state.save_credentials("kite", {"api_key": "k1"})
    state.save_credentials("groww", {"api_key": "g1"})
    result = state.load_most_recent()
    assert result == ("groww", {"api_key": "g1"})


def test_list_providers_returns_every_stored_provider(isolated_state: Path) -> None:
    state.save_credentials("kite", {"api_key": "k1"})
    state.save_credentials("groww", {"api_key": "g1"})
    assert set(state.list_providers()) == {"kite", "groww"}


def test_credentials_db_has_owner_only_permissions(isolated_state: Path) -> None:
    state.save_credentials("kite", {"api_key": "k1"})
    mode = oct(isolated_state.stat().st_mode & 0o777)
    assert mode == "0o600"
