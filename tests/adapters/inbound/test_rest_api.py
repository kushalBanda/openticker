"""REST routes end to end, over HTTP in-process, with `FakeBrokerPort`
registered under its own name so nothing touches Kite."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.rest_api import create_app
from openticker.composition import build_event_bus
from openticker.events.bus import EventBus
from openticker.use_cases.api_keys import create_api_key, revoke
from tests.fixtures.fake_broker import FAKE_LAST_PRICE, FakeBrokerPort

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST

# Every MCP tool and the route that mirrors it.
ROUTE_FOR_TOOL = {
    "get_broker_login_url": ("GET", "/api/v1/brokers/{broker}/login-url"),
    "connect_broker": ("POST", "/api/v1/brokers/connect"),
    "sync_instruments": ("POST", "/api/v1/instruments/sync"),
    "search_instruments": ("GET", "/api/v1/instruments"),
    "get_quote": ("GET", "/api/v1/quote"),
    "get_historical_bars": ("GET", "/api/v1/bars"),
    "get_option_chain": ("GET", "/api/v1/option-chain"),
    "place_order": ("POST", "/api/v1/orders"),
    "get_orderbook": ("GET", "/api/v1/orders"),
    "get_positions": ("GET", "/api/v1/positions"),
    "get_funds": ("GET", "/api/v1/funds"),
    "evaluate_risk": ("POST", "/api/v1/risk/evaluate"),
    "get_audit_log": ("GET", "/api/v1/audit"),
    "get_market_status": ("GET", "/api/v1/market-status"),
}


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method.upper(), path) for path, item in app.openapi()["paths"].items() for method in item
    }


@pytest.fixture(autouse=True)
def _fake_broker_registered() -> Iterator[None]:
    registry.register("fake", FakeBrokerPort)
    yield
    del registry.BROKER_REGISTRY["fake"]


@pytest.fixture
def events() -> Iterator[EventBus]:
    bus = build_event_bus({})
    yield bus
    bus.close()


@pytest.fixture
def key() -> str:
    return create_api_key("tests", NOW)[1]


@pytest.fixture
def client(events: EventBus, key: str) -> TestClient:
    return TestClient(create_app(events, {}, clock=lambda: NOW), headers={"X-API-Key": key})


def test_rest_rejects_missing_wrong_and_revoked_api_keys(events: EventBus, key: str) -> None:
    app = create_app(events, {})
    anonymous = TestClient(app)

    assert anonymous.get("/health").status_code == 200
    assert anonymous.get("/api/v1/funds", params={"broker": "fake"}).status_code == 401
    wrong = anonymous.get(
        "/api/v1/funds", params={"broker": "fake"}, headers={"X-API-Key": "otk_x"}
    )
    assert wrong.status_code == 401 and "keys create" in wrong.json()["detail"]

    authorized = {"X-API-Key": key}
    assert anonymous.get("/api/v1/funds", params={"broker": "fake"}, headers=authorized).is_success
    revoke("tests", NOW)
    assert (
        anonymous.get("/api/v1/funds", params={"broker": "fake"}, headers=authorized).status_code
        == 401
    )


def test_every_route_but_health_needs_a_key(events: EventBus) -> None:
    app = create_app(events, {})
    anonymous = TestClient(app)
    routes = _routes(app) - {("GET", "/health")}

    assert len(routes) == len(ROUTE_FOR_TOOL)
    for method, path in routes:
        response = anonymous.request(method, path.replace("{broker}", "fake"))
        assert response.status_code == 401, path


def test_every_mcp_tool_has_a_rest_route(events: EventBus) -> None:
    tools = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(ROUTE_FOR_TOOL) == tools
    assert set(ROUTE_FOR_TOOL.values()) <= _routes(create_app(events, {}))


def test_sandbox_round_trip_over_rest(client: TestClient) -> None:
    assert client.post("/api/v1/instruments/sync", json={"broker": "fake"}).json() == {
        "broker": "fake",
        "instrument_count": 1,
    }
    order = {
        "broker": "fake",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 4,
        "product": "MIS",
    }

    placed = client.post("/api/v1/orders", json=order).json()
    positions = client.get("/api/v1/positions", params={"broker": "fake"}).json()
    funds = client.get("/api/v1/funds", params={"broker": "fake"}).json()
    book = client.get("/api/v1/orders", params={"broker": "fake"}).json()
    audit = client.get("/api/v1/audit", params={"event_type": "OrderFilled"}).json()

    assert (placed["status"], placed["fill_price"]) == ("FILLED", FAKE_LAST_PRICE)
    assert [(p["symbol"], p["quantity"]) for p in positions["positions"]] == [("RELIANCE", 4)]
    assert funds["used_margin"] == 4 * FAKE_LAST_PRICE / 5
    assert [entry["order_id"] for entry in book["orders"]] == [placed["order_id"]]
    assert book["orders"][0]["triggered_by"] == "rest:tests"
    assert audit["entries"][0]["triggered_by"] == "rest:tests"


def test_a_rejected_order_is_a_normal_response_with_its_reason(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})

    response = client.post(
        "/api/v1/orders",
        json={
            "broker": "fake",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": "SELL",
            "quantity": 1,
            "product": "CNC",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED" and "sold short" in response.json()["reason"]


def test_fixable_errors_become_http_statuses_with_their_message(client: TestClient) -> None:
    quote = {"broker": "fake", "symbol": "RELIANCE", "exchange": "NSE"}

    unsynced = client.get("/api/v1/quote", params=quote)
    unknown_broker = client.get("/api/v1/quote", params={**quote, "broker": "nonexistent"})
    bad_exchange = client.get("/api/v1/quote", params={**quote, "exchange": "NYSE"})

    assert unsynced.status_code == 404 and "sync_instruments" in unsynced.json()["detail"]
    assert unknown_broker.status_code == 404
    assert "no broker adapter registered" in unknown_broker.json()["detail"]
    assert bad_exchange.status_code == 422


def test_quote_and_risk_match_the_mcp_results(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})

    quote = client.get(
        "/api/v1/quote", params={"broker": "fake", "symbol": "RELIANCE", "exchange": "NSE"}
    ).json()
    risk = client.post(
        "/api/v1/risk/evaluate",
        json={
            "broker": "fake",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": "BUY",
            "quantity": 1,
            "stop_loss": FAKE_LAST_PRICE + 10,
        },
    ).json()

    assert quote["last_price"] == FAKE_LAST_PRICE and quote["as_of"].endswith("+05:30")
    assert risk["breached"] and risk["reason"] == "stop_loss" and risk["warnings"]


def test_market_status_route(client: TestClient) -> None:
    [nse] = client.get("/api/v1/market-status", params={"exchange": "NSE"}).json()["exchanges"]

    assert nse["is_open"] and nse["session_closes_at"] == "2026-09-22T15:30:00+05:30"
