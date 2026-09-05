from datetime import UTC, datetime
from http import HTTPStatus

import pytest
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
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-31T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {"bars": []}


def test_get_bars_returns_already_cached_bars_without_calling_provider(
    client: TestClient,
    duckdb_store: DuckDBStore,
    fake_adapter: FakeAdapter,
    auth_headers: dict[str, str],
) -> None:
    duckdb_store.write_bars([_bar(1), _bar(2)])
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert len(body["bars"]) == 2
    assert body["bars"][0]["symbol"] == "NSE-RELIANCE"
    assert fake_adapter.fetch_historical_calls == 0


def test_get_bars_fetches_live_when_nothing_cached(
    client: TestClient, fake_adapter: FakeAdapter, auth_headers: dict[str, str]
) -> None:
    fake_adapter.bars = [_bar(1), _bar(2)]
    resp = client.get(
        "/market/bars",
        params={
            "symbol": "NSE-RELIANCE",
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-02T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    assert len(resp.json()["bars"]) == 2
    assert fake_adapter.fetch_historical_calls == 1


def test_get_bars_fetches_only_the_missing_edges(
    client: TestClient,
    duckdb_store: DuckDBStore,
    fake_adapter: FakeAdapter,
    auth_headers: dict[str, str],
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
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    assert len(resp.json()["bars"]) == 3
    assert fake_adapter.fetch_historical_calls == 2


def test_fetch_index_constituents_then_get_returns_them(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(index_name: str) -> list[str]:
        return ["RELIANCE", "TCS"]

    monkeypatch.setattr(
        "server.routers.market.fetch_index_constituents", fake_fetch
    )
    resp = client.post(
        "/market/index-constituents/NIFTY50/fetch", headers=auth_headers
    )
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert body["index_name"] == "NIFTY50"
    assert body["symbols"] == ["RELIANCE", "TCS"]
    year = body["year"]

    resp = client.get(
        "/market/index-constituents",
        params={"index_name": "NIFTY50", "year": year},
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["symbols"] == ["RELIANCE", "TCS"]


def test_get_index_constituents_empty_when_nothing_stored(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get(
        "/market/index-constituents",
        params={"index_name": "NIFTY500", "year": 2026},
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["symbols"] == []


def test_fetch_index_constituents_rejects_unknown_index(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/market/index-constituents/BOGUS/fetch", headers=auth_headers
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
