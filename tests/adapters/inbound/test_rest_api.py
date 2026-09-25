
"""REST routes end to end, over HTTP in-process, with `FakeBrokerPort`
registered under its own name so nothing touches Kite."""

import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.rest_api import HideAlertTokens, create_app
from openticker.composition import build_event_bus
from openticker.events.bus import EventBus
from openticker.use_cases.api_keys import create_api_key, revoke
from tests.fixtures.fake_broker import FAKE_ASK, FAKE_LAST_PRICE, FakeBrokerPort

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST

# Every MCP tool and the route that mirrors it.
ROUTE_FOR_TOOL = {
    "get_broker_login_url": ("GET", "/api/v1/brokers/{broker}/login-url"),
    "connect_broker": ("POST", "/api/v1/brokers/connect"),
    "sync_instruments": ("POST", "/api/v1/instruments/sync"),
    "search_instruments": ("GET", "/api/v1/instruments"),
    "get_quote": ("GET", "/api/v1/quote"),
    "get_quotes": ("POST", "/api/v1/quotes"),
    "get_market_depth": ("GET", "/api/v1/depth"),
    "get_historical_bars": ("GET", "/api/v1/bars"),
    "get_option_chain": ("GET", "/api/v1/option-chain"),
    "place_order": ("POST", "/api/v1/orders"),
    "place_basket": ("POST", "/api/v1/orders/basket"),
    "get_margin": ("POST", "/api/v1/margin"),
    "preview_charges": ("GET", "/api/v1/charges/preview"),
    "check_charge_rates": ("POST", "/api/v1/charges/check"),
    "get_orderbook": ("GET", "/api/v1/orders"),
    "get_positions": ("GET", "/api/v1/positions"),
    "get_funds": ("GET", "/api/v1/funds"),
    "evaluate_risk": ("POST", "/api/v1/risk/evaluate"),
    "get_audit_log": ("GET", "/api/v1/audit"),
    "get_market_status": ("GET", "/api/v1/market-status"),
    "cancel_order": ("DELETE", "/api/v1/orders/{order_id}"),
    "cancel_all_orders": ("POST", "/api/v1/orders/cancel-all"),
    "close_position": ("POST", "/api/v1/positions/close"),
    "close_all_positions": ("POST", "/api/v1/positions/close-all"),
    "modify_order": ("PATCH", "/api/v1/orders/{order_id}"),
    "get_order_status": ("GET", "/api/v1/orders/{order_id}"),
    "get_tradebook": ("GET", "/api/v1/trades"),
    "create_strategy": ("POST", "/api/v1/strategies"),
    "list_strategies": ("GET", "/api/v1/strategies"),
    "get_strategy": ("GET", "/api/v1/strategies/{strategy_id}"),
    "update_strategy": ("PUT", "/api/v1/strategies/{strategy_id}"),
    "delete_strategy": ("DELETE", "/api/v1/strategies/{strategy_id}"),
    "preview_strategy": ("GET", "/api/v1/strategies/{strategy_id}/preview"),
    "start_strategy": ("POST", "/api/v1/strategies/{strategy_id}/start"),
    "stop_strategy": ("POST", "/api/v1/strategies/{strategy_id}/stop"),
    "kill_strategy": ("POST", "/api/v1/strategies/{strategy_id}/kill"),
    "release_kill_switch": ("POST", "/api/v1/strategies/{strategy_id}/release"),
    "schedule_strategy": ("POST", "/api/v1/strategies/{strategy_id}/schedule"),
    "unschedule_strategy": ("DELETE", "/api/v1/strategies/{strategy_id}/schedule"),
    "close_strategy_leg": ("POST", "/api/v1/strategies/{strategy_id}/legs/{leg_id}/close"),
    "get_strategy_runs": ("GET", "/api/v1/strategies/{strategy_id}/runs"),
    "get_strategy_ledger": ("GET", "/api/v1/strategies/{strategy_id}/ledger"),
    "get_strategy_run": ("GET", "/api/v1/runs/{run_id}"),
    "create_signal_strategy": ("POST", "/api/v1/signal-strategies"),
    "update_signal_strategy": ("PUT", "/api/v1/signal-strategies/{strategy_id}"),
    "rotate_strategy_webhook": ("POST", "/api/v1/strategies/{strategy_id}/webhook"),
    "disable_strategy_webhook": ("DELETE", "/api/v1/strategies/{strategy_id}/webhook"),
    "get_strategy_signals": ("GET", "/api/v1/strategies/{strategy_id}/signals"),
    "upload_script": ("POST", "/api/v1/scripts"),
    "list_scripts": ("GET", "/api/v1/scripts"),
    "get_script": ("GET", "/api/v1/scripts/{script_id}"),
    "update_script": ("PUT", "/api/v1/scripts/{script_id}"),
    "delete_script": ("DELETE", "/api/v1/scripts/{script_id}"),
    "start_script": ("POST", "/api/v1/scripts/{script_id}/start"),
    "stop_script": ("POST", "/api/v1/scripts/{script_id}/stop"),
    "schedule_script": ("POST", "/api/v1/scripts/{script_id}/schedule"),
    "unschedule_script": ("DELETE", "/api/v1/scripts/{script_id}/schedule"),
    "get_script_logs": ("GET", "/api/v1/scripts/{script_id}/logs"),
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


def test_every_route_but_health_and_alerts_needs_a_key(events: EventBus) -> None:
    app = create_app(events, {})
    anonymous = TestClient(app)
    routes = _routes(app) - {("GET", "/health"), ("POST", "/webhooks/strategies/{token}")}

    assert len(routes) == len(ROUTE_FOR_TOOL)
    for method, path in routes:
        response = anonymous.request(
            method,
            path.replace("{broker}", "fake")
            .replace("{order_id}", "SB1")
            .replace("{strategy_id}", "stg_1")
            .replace("{script_id}", "scr_1"),
        )
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

    assert (placed["status"], placed["fill_price"]) == ("FILLED", FAKE_ASK)
    assert [(p["symbol"], p["quantity"]) for p in positions["positions"]] == [("RELIANCE", 4)]
    assert funds["used_margin"] == round(4 * FAKE_ASK / 5, 2)
    assert funds["charges"] > 0
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


def test_resting_order_and_cancel_over_rest(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    placed = client.post(
        "/api/v1/orders",
        json={
            "broker": "fake",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": "SELL",
            "quantity": 1,
            "product": "MIS",
            "order_type": "SL-M",
            "trigger_price": FAKE_LAST_PRICE - 50,
        },
    ).json()

    cancelled = client.delete(f"/api/v1/orders/{placed['order_id']}", params={"broker": "fake"})
    missing = client.delete("/api/v1/orders/SBNOPE", params={"broker": "fake"})

    assert placed["status"] == "PENDING"
    assert cancelled.json()["status"] == "CANCELLED"
    assert missing.status_code == 404


def test_order_status_and_tradebook_over_rest(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    order = {
        "broker": "fake",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 2,
        "product": "MIS",
    }
    placed = client.post("/api/v1/orders", json=order).json()

    status = client.get(f"/api/v1/orders/{placed['order_id']}", params={"broker": "fake"})
    missing = client.get("/api/v1/orders/SBNOPE", params={"broker": "fake"})
    trades = client.get("/api/v1/trades", params={"broker": "fake"}).json()

    assert (status.json()["status"], status.json()["fill_price"]) == ("FILLED", FAKE_ASK)
    assert missing.status_code == 404
    [trade] = trades["trades"]
    assert (trade["order_id"], trade["quantity"], trade["value"]) == (
        placed["order_id"],
        2,
        2 * FAKE_ASK,
    )
    assert (trade["expected_price"], trade["charges"] > 0) == (FAKE_LAST_PRICE, True)
    assert trade["triggered_by"] == "rest:tests"
    assert trade["filled_at"] == "2026-09-22T09:30:00+05:30"  # the app's clock, not the wall's
    assert trades["since"] == "2026-09-22T00:00:00+05:30"


def test_basket_route_places_buys_first(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    leg = {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 2, "product": "MIS"}

    placed = client.post(
        "/api/v1/orders/basket",
        json={"broker": "fake", "orders": [{**leg, "side": "SELL"}, {**leg, "side": "BUY"}]},
    ).json()
    too_many = client.post(
        "/api/v1/orders/basket",
        json={"broker": "fake", "orders": [{**leg, "side": "BUY"}] * 51},
    )
    book = client.get("/api/v1/orders", params={"broker": "fake"}).json()

    assert [(o["side"], o["status"]) for o in placed["orders"]] == [
        ("BUY", "FILLED"),
        ("SELL", "FILLED"),
    ]
    assert too_many.status_code == 422
    assert [o["triggered_by"] for o in book["orders"]] == ["rest:tests"] * 2


def test_close_and_cancel_all_routes(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    base = {"broker": "fake", "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS"}
    client.post("/api/v1/orders", json={**base, "side": "BUY", "quantity": 3})
    client.post(
        "/api/v1/orders",
        json={**base, "side": "BUY", "quantity": 1, "order_type": "LIMIT", "price": 2000},
    )

    closed = client.post("/api/v1/positions/close", json=base).json()
    again = client.post("/api/v1/positions/close", json=base)
    close_all = client.post("/api/v1/positions/close-all", json={"broker": "fake"}).json()
    cancelled = client.post("/api/v1/orders/cancel-all", json={"broker": "fake"}).json()

    assert (closed["side"], closed["quantity"], closed["status"]) == ("SELL", 3, "FILLED")
    assert again.status_code == 404 and "get_positions" in again.json()["detail"]
    assert close_all == {"orders": []}
    assert len(cancelled["cancelled"]) == 1 and cancelled["failed"] == []


def test_charges_preview_route_matches_the_tool(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    order: dict[str, str | float] = {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 10, "price": 1226.0}

    sold = client.get("/api/v1/charges/preview", params={**order, "side": "SELL", "product": "MIS"})
    unknown = client.get(
        "/api/v1/charges/preview",
        params={**order, "symbol": "NOPE", "side": "SELL", "product": "MIS"},
    )

    assert (sold.status_code, sold.json()["total"]) == (200, 7.86)
    assert unknown.status_code == 404


def test_charges_check_route_matches_the_tool(client: TestClient) -> None:
    before_sync = client.post("/api/v1/charges/check", json={"broker": "fake"})
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})

    checked = client.post("/api/v1/charges/check", json={"broker": "fake"})

    assert before_sync.status_code == 404
    assert "RELIANCE is not in the instrument list" in before_sync.json()["detail"]
    assert checked.status_code == 200
    assert checked.json()["matches"] is True and len(checked.json()["samples"]) == 4


def test_margin_route_matches_the_tool(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    leg = {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 2, "product": "MIS"}

    margin = client.post(
        "/api/v1/margin",
        json={"broker": "fake", "orders": [{**leg, "side": "BUY"}, {**leg, "side": "SELL"}]},
    ).json()
    bad = client.post(
        "/api/v1/margin",
        json={"broker": "fake", "orders": [{**leg, "side": "BUY", "order_type": "LIMIT"}]},
    )

    assert (margin["total"], margin["benefit"]) == (2 * FAKE_LAST_PRICE * 1.2 - 1000, 1000)
    assert "sandbox" in margin["note"]
    assert bad.status_code == 422 and "order 1" in bad.json()["detail"]
    assert client.get("/api/v1/orders", params={"broker": "fake"}).json()["orders"] == []


def test_strategy_routes_mirror_the_tools(client: TestClient) -> None:
    from tests.adapters.inbound.test_mcp_server import STRADDLE_JSON
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    body = {"name": "nifty straddle", "definition": STRADDLE_JSON}

    created = client.post("/api/v1/strategies", json=body)
    strategy_id = created.json()["strategy_id"]
    duplicate = client.post("/api/v1/strategies", json=body)
    preview = client.get(f"/api/v1/strategies/{strategy_id}/preview", params={"broker": "fake"})
    late = client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={**body, "definition": {**STRADDLE_JSON, "exit_time": "15:25"}},
    )
    malformed = client.post("/api/v1/strategies", json={"name": "x", "definition": {}})

    assert created.status_code == 200
    assert created.json()["definition"]["exit_time"] == "15:15:00"
    assert duplicate.status_code == 409 and "already exists" in duplicate.json()["detail"]
    assert [leg["label"] for leg in preview.json()["legs"]] == ["ATM", "ATM"]
    assert late.status_code == 422 and "15:15" in late.json()["detail"]
    assert malformed.status_code == 422
    assert client.get("/api/v1/strategies").json()["strategies"][0]["name"] == "nifty straddle"
    assert client.delete(f"/api/v1/strategies/{strategy_id}").json()["deleted"] is True
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 404


def test_schedule_routes_mirror_the_tools(client: TestClient) -> None:
    from tests.adapters.inbound.test_mcp_server import STRADDLE_JSON
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    body = {"name": "scheduled", "definition": STRADDLE_JSON}
    strategy_id = client.post("/api/v1/strategies", json=body).json()["strategy_id"]
    base = f"/api/v1/strategies/{strategy_id}/schedule"

    scheduled = client.post(base, json={"broker": "fake"})
    unknown = client.post(base, json={"broker": "nope"})
    unscheduled = client.delete(base)

    assert scheduled.status_code == 200 and scheduled.json()["scheduled_broker"] == "fake"
    assert unknown.status_code == 404
    assert unscheduled.json()["scheduled_broker"] is None
    client.post(f"/api/v1/strategies/{strategy_id}/kill")
    assert client.post(base, json={"broker": "fake"}).status_code == 409


def test_strategy_run_routes_mirror_the_tools(client: TestClient) -> None:
    from openticker.use_cases.strategies.runner import process_commands
    from tests.adapters.inbound.test_mcp_server import STRADDLE_JSON
    from tests.fixtures.strategy_desk import Desk

    desk = Desk()
    body = {"name": "nifty straddle", "definition": STRADDLE_JSON}
    strategy_id = client.post("/api/v1/strategies", json=body).json()["strategy_id"]
    base = f"/api/v1/strategies/{strategy_id}"

    started = client.post(f"{base}/start", json={"broker": "fake"})
    again = client.post(f"{base}/start", json={"broker": "fake"})
    process_commands(desk.context, desk.now)
    runs = client.get(f"{base}/runs").json()
    run_id = runs["runs"][0]["run_id"]
    busy = client.put(base, json=body)
    closed = client.post(f"{base}/legs/leg2/close")
    process_commands(desk.context, desk.now)
    run = client.get(f"/api/v1/runs/{run_id}").json()
    stopped = client.post(f"{base}/stop")
    process_commands(desk.context, desk.now)

    assert started.status_code == 200 and started.json()["status"] == "pending"
    assert again.status_code == 409 and "already starting" in again.json()["detail"]
    assert runs["runs"][0]["trigger"] == "rest:tests"
    assert busy.status_code == 409 and "stop the strategy" in busy.json()["detail"]
    assert closed.json()["command"] == "close_leg"
    assert [leg["status"] for leg in run["legs"]] == ["open", "closed"]
    assert stopped.status_code == 200
    assert client.get(f"{base}/runs").json()["runs"][0]["stop_reason"] == "manual"
    assert client.post(f"{base}/stop").status_code == 409
    assert client.get("/api/v1/runs/run_missing").status_code == 404
    ledger = client.get(f"{base}/ledger", params={"limit": 1}).json()
    assert (ledger["total_runs"], ledger["uncharged"], len(ledger["runs"])) == (1, 1, 1)
    assert client.get("/api/v1/strategies/stg_nope/ledger").status_code == 404


def test_an_alert_posted_to_its_url_needs_no_api_key(client: TestClient, events: EventBus) -> None:
    from tests.adapters.inbound.test_mcp_server import SIGNAL_JSON
    from tests.fixtures.strategies import list_nifty_market

    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    list_nifty_market()
    created = client.post(
        "/api/v1/signal-strategies", json={"name": "alerts", "definition": SIGNAL_JSON}
    )
    strategy_id = created.json()["strategy_id"]
    base = f"/api/v1/strategies/{strategy_id}"
    webhook = client.post(f"{base}/webhook", json={"broker": "fake"}).json()
    anonymous = TestClient(create_app(events, {}, clock=lambda: NOW))  # 09:30 IST

    accepted = anonymous.post(
        webhook["alert_path"], json={"stocks": "RELIANCE", "scan_name": "BUY"}
    )
    repeated = anonymous.post(
        webhook["alert_path"], json={"stocks": "RELIANCE", "scan_name": "BUY"}
    )
    refused = anonymous.post(webhook["alert_path"], content=b"nope")
    unknown = anonymous.post("/webhooks/strategies/otw_" + "x" * 43, json={})
    changed = client.put(
        f"/api/v1/signal-strategies/{strategy_id}",
        json={"name": "alerts", "definition": {**SIGNAL_JSON, "exit_time": "15:10"}},
    )
    signals = client.get(f"{base}/signals").json()
    disabled = client.delete(f"{base}/webhook")
    gone = anonymous.post(webhook["alert_path"], json={"stocks": "RELIANCE", "scan_name": "BUY"})

    assert created.status_code == 200 and created.json()["kind"] == "signal"
    assert webhook["alert_url"] is None and webhook["broker"] == "fake"
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted", "message": "leg1 long_entry queued"}
    assert repeated.status_code == 200  # the runner makes a second entry a no-op
    assert (refused.status_code, refused.json()["status"]) == (400, "refused")
    assert (unknown.status_code, unknown.json()["status"]) == (404, "unknown")
    assert changed.json()["definition"]["exit_time"] == "15:10:00"
    assert [call["result"] for call in signals["calls"]] == ["refused", "accepted", "accepted"]
    assert disabled.status_code == 200 and gone.status_code == 404
    assert client.get(f"{base}/preview", params={"broker": "fake"}).status_code == 409


def test_the_access_log_never_shows_an_alert_token() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", "/webhooks/strategies/otw_secretsecretsecret?x=1", "1.1", 200),
        None,
    )

    assert HideAlertTokens().filter(record)
    assert "otw_" not in record.getMessage()
    assert "/webhooks/strategies/[token]?x=1" in record.getMessage()


SCRIPT_ROUTES = {
    ("GET", "/api/v1/instruments"),
    ("GET", "/api/v1/quote"),
    ("POST", "/api/v1/quotes"),
    ("GET", "/api/v1/depth"),
    ("GET", "/api/v1/bars"),
    ("GET", "/api/v1/option-chain"),
    ("GET", "/api/v1/market-status"),
    ("POST", "/api/v1/risk/evaluate"),
    ("POST", "/api/v1/margin"),
    ("POST", "/api/v1/orders"),
    ("POST", "/api/v1/orders/basket"),
    ("GET", "/api/v1/orders"),
    ("DELETE", "/api/v1/orders/{order_id}"),
    ("PATCH", "/api/v1/orders/{order_id}"),
    ("GET", "/api/v1/orders/{order_id}"),
    ("GET", "/api/v1/trades"),
    ("GET", "/api/v1/positions"),
    ("POST", "/api/v1/positions/close"),
    ("GET", "/api/v1/funds"),
}


def test_script_api_key_cannot_connect_broker_or_manage_anything(events: EventBus) -> None:
    from openticker.use_cases.api_keys import create_script_key

    app = create_app(events, {}, clock=lambda: NOW)
    script = TestClient(app, headers={"X-API-Key": create_script_key("scr_1", "srn_1", NOW)})
    routes = _routes(app) - {("GET", "/health"), ("POST", "/webhooks/strategies/{token}")}

    assert SCRIPT_ROUTES < routes
    for method, path in routes:
        response = script.request(
            method,
            path.replace("{broker}", "fake")
            .replace("{order_id}", "SB1")
            .replace("{strategy_id}", "stg_1")
            .replace("{script_id}", "scr_1")
            .replace("{run_id}", "run_1")
            .replace("{leg_id}", "leg1"),
        )
        if (method, path) in SCRIPT_ROUTES:
            assert response.status_code != 403, path
        else:
            assert response.status_code == 403, path
            assert response.json()["detail"] == (
                "a script's key reaches prices, orders and positions only"
            )


def test_a_scripts_orders_name_the_script(client: TestClient, events: EventBus) -> None:
    from openticker.use_cases.api_keys import create_script_key

    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    script = TestClient(
        create_app(events, {}, clock=lambda: NOW),
        headers={"X-API-Key": create_script_key("scr_1", "srn_1", NOW)},
    )
    order = {
        "broker": "fake",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 1,
        "product": "MIS",
    }

    placed = script.post("/api/v1/orders", json=order).json()

    assert placed["status"] == "FILLED"
    book = script.get("/api/v1/orders", params={"broker": "fake"}).json()
    assert book["orders"][0]["triggered_by"] == "script:scr_1"
    assert script.get("/api/v1/funds", params={"broker": "fake"}).is_success


def test_script_routes_mirror_the_tools(client: TestClient) -> None:
    created = client.post("/api/v1/scripts", json={"name": "pinger", "source": "print(1)\n"})
    assert created.status_code == 200
    script_id = created.json()["script_id"]

    assert (
        client.post("/api/v1/scripts", json={"name": "bad", "source": "def (:"}).status_code == 422
    )
    assert client.post("/api/v1/scripts", json={"name": "pinger", "source": "1"}).status_code == 409
    assert client.get(f"/api/v1/scripts/{script_id}/logs").status_code == 409
    assert client.post(f"/api/v1/scripts/{script_id}/stop").status_code == 409
    assert client.get("/api/v1/scripts/scr_missing").status_code == 404
    started = client.post(f"/api/v1/scripts/{script_id}/start").json()
    assert (started["command"]["command"], started["command"]["triggered_by"]) == (
        "start",
        "rest:tests",
    )
    assert (
        client.put(
            f"/api/v1/scripts/{script_id}", json={"name": "pinger", "source": "print(2)\n"}
        ).status_code
        == 409
    )
    client.post(f"/api/v1/scripts/{script_id}/stop")
    scheduled = client.post(
        f"/api/v1/scripts/{script_id}/schedule", json={"start_time": "09:20", "stop_time": "15:00"}
    ).json()
    assert scheduled["schedule"]["stop_time"] == "15:00:00"
    assert client.delete(f"/api/v1/scripts/{script_id}/schedule").json()["schedule"] is None
    detail = client.get(f"/api/v1/scripts/{script_id}", params={"include_source": True}).json()
    assert detail["source"] == "print(1)\n"
    assert [s["name"] for s in client.get("/api/v1/scripts").json()["scripts"]] == ["pinger"]
    assert client.delete(f"/api/v1/scripts/{script_id}").json() == {
        "script_id": script_id,
        "deleted": True,
    }


def test_modify_route_changes_a_resting_order(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    placed = client.post(
        "/api/v1/orders",
        json={
            "broker": "fake",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "side": "BUY",
            "quantity": 2,
            "product": "MIS",
            "order_type": "LIMIT",
            "price": 2400.0,
        },
    ).json()
    path = f"/api/v1/orders/{placed['order_id']}"

    changed = client.patch(path, json={"broker": "fake", "price": 2410.0, "quantity": 4}).json()
    refused = client.patch(path, json={"broker": "fake", "trigger_price": 2400.0}).json()
    missing = client.patch("/api/v1/orders/SBNOPE", json={"broker": "fake", "price": 1.0})

    assert changed["status"] == "PENDING"
    assert (changed["order"]["price"], changed["order"]["quantity"]) == (2410.0, 4)
    assert refused["status"] == "REJECTED" and "take no trigger_price" in refused["reason"]
    assert refused["order"]["price"] == 2410.0
    assert missing.status_code == 404
    audit = client.get("/api/v1/audit", params={"event_type": "OrderModified"}).json()
    [modified] = audit["entries"]
    assert modified["triggered_by"] == "rest:tests"


def test_quotes_route_lists_what_it_could_not_quote(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})

    def body(*symbols: str) -> dict[str, object]:
        instruments = [{"symbol": symbol, "exchange": "NSE"} for symbol in symbols]
        return {"broker": "fake", "instruments": instruments}

    ok = client.post("/api/v1/quotes", json=body("RELIANCE", "NOPE")).json()
    none_known = client.post("/api/v1/quotes", json=body("NOPE"))
    too_many = client.post("/api/v1/quotes", json=body(*(f"S{i}" for i in range(51))))

    assert [(q["symbol"], q["last_price"]) for q in ok["quotes"]] == [("RELIANCE", FAKE_LAST_PRICE)]
    assert [(m["symbol"], m["exchange"]) for m in ok["missing"]] == [("NOPE", "NSE")]
    assert none_known.status_code == 404
    assert too_many.status_code == 422


def test_depth_route_matches_the_tool(client: TestClient) -> None:
    client.post("/api/v1/instruments/sync", json={"broker": "fake"})
    params = {"broker": "fake", "symbol": "RELIANCE", "exchange": "NSE"}

    depth = client.get("/api/v1/depth", params=params).json()
    unknown = client.get("/api/v1/depth", params={**params, "symbol": "NOPE"})

    assert [(b["price"], b["quantity"], b["orders"]) for b in depth["bids"]] == [
        (FAKE_LAST_PRICE - 0.05, 10, 2),
        (FAKE_LAST_PRICE - 0.1, 40, 3),
    ]
    assert (depth["total_buy_quantity"], depth["total_sell_quantity"]) == (900, 700)
    assert unknown.status_code == 404
