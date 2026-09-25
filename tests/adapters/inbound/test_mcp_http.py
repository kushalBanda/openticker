"""MCP over HTTP on openticker-serve (ADR 29): the same tools as stdio, held
to the caller's key by REST's scope table."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.mcp_scoped import WithMcp
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.scopes import REVIEW_ROUTES, TOOL_ROUTES
from openticker.composition import build_event_bus
from openticker.use_cases.api_keys import create_api_key, create_review_key, create_script_key

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    events = build_event_bus({})
    with TestClient(WithMcp(create_app(events, {}), mcp_server.mcp)) as client:
        yield client
    events.close()


def _rpc(client: TestClient, method: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
    response = client.post(
        "/mcp",
        headers={**HEADERS, **headers},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _tools(client: TestClient, headers: dict[str, str]) -> set[str]:
    return {tool["name"] for tool in _rpc(client, "tools/list", {}, headers)["tools"]}


def _call(client: TestClient, headers: dict[str, str], tool: str, **arguments: Any) -> str:
    result = _rpc(client, "tools/call", {"name": tool, "arguments": arguments}, headers)
    text: str = result["content"][0]["text"]
    return text


def test_mcp_needs_a_key(client: TestClient) -> None:
    missing = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1})
    wrong = client.post("/mcp", headers={**HEADERS, "x-api-key": "otk_nope"}, json={})

    assert missing.status_code == wrong.status_code == 401
    assert "X-API-Key" in missing.json()["detail"]


def test_a_full_key_sees_every_tool_by_header_or_bearer(client: TestClient) -> None:
    _, key = create_api_key("desk", NOW)

    assert _tools(client, {"x-api-key": key}) == set(TOOL_ROUTES)
    assert _tools(client, {"authorization": f"Bearer {key}"}) == set(TOOL_ROUTES)


def test_a_review_key_sees_only_what_its_scope_reads(client: TestClient) -> None:
    key = create_review_key("stg_mine", "job_1", NOW)
    readable = {tool for tool, route in TOOL_ROUTES.items() if route in REVIEW_ROUTES}

    assert _tools(client, {"authorization": f"Bearer {key}"}) == readable
    assert "get_strategy_ledger" in readable and "place_order" not in readable


def test_a_review_key_is_refused_other_calls_even_by_name(client: TestClient) -> None:
    headers = {"x-api-key": create_review_key("stg_mine", "job_1", NOW)}

    placed = _call(client, headers, "place_order", broker="fake")
    theirs = _call(client, headers, "get_strategy_ledger", strategy_id="stg_theirs")
    own = _call(client, headers, "get_strategy_ledger", strategy_id="stg_mine")

    assert placed.startswith("place_order refused")
    assert "reads strategy stg_mine only" in theirs
    assert "no strategy with id 'stg_mine'" in own  # allowed through; it just doesn't exist


def test_a_scripts_key_gets_the_same_tools_over_mcp_as_over_rest(client: TestClient) -> None:
    headers = {"x-api-key": create_script_key("scr_1", "run_1", NOW)}

    tools = _tools(client, headers)

    assert "place_order" in tools and "start_strategy" not in tools
