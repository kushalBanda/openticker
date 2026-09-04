from datetime import UTC, datetime
from http import HTTPStatus

from fastapi.testclient import TestClient
from ingest.core.models import Bar
from ingest.storage.duckdb_store import DuckDBStore

from ..conftest import FakeAdapter


def _bar(day: int) -> Bar:
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, day, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
        provider="kite",
    )


def test_get_bars_empty_when_nothing_cached_and_provider_has_nothing(
    client: TestClient,
) -> None:
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-31T00:00:00Z",
        },
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {"bars": []}


def test_get_bars_returns_already_cached_bars_without_calling_provider(
    client: TestClient, duckdb_store: DuckDBStore, fake_adapter: FakeAdapter
) -> None:
    duckdb_store.write_bars([_bar(1), _bar(2)])
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert len(body["bars"]) == 2
    assert body["bars"][0]["symbol"] == "NSE-RELIANCE"
    assert fake_adapter.fetch_historical_calls == 0


def test_get_bars_fetches_live_when_nothing_cached(
    client: TestClient, fake_adapter: FakeAdapter
) -> None:
    fake_adapter.bars = [_bar(1), _bar(2)]
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
        },
    )
    assert resp.status_code == HTTPStatus.OK
    assert len(resp.json()["bars"]) == 2
    assert fake_adapter.fetch_historical_calls == 1


def test_get_bars_fetches_only_the_missing_edges(
    client: TestClient, duckdb_store: DuckDBStore, fake_adapter: FakeAdapter
) -> None:
    # Middle of the range is already cached; requested range extends a day
    # on each side. DataEngine should fetch only those two edges, not
    # re-fetch what's already there.
    duckdb_store.write_bars([_bar(2)])
    fake_adapter.bars = [_bar(1), _bar(2), _bar(3)]

    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-03T00:00:00Z",
        },
    )
    assert resp.status_code == HTTPStatus.OK
    assert len(resp.json()["bars"]) == 3
    assert fake_adapter.fetch_historical_calls == 2
