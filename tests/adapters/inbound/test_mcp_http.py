"""MCP over HTTP on openticker-serve (ADR 29): the same tools as stdio, held
to the caller's key by REST's scope table."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.mcp_scoped import WithMcp
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.scopes import REVIEW_ROUTES, TOOL_ROUTES
from openticker.composition import build_event_bus
from openticker.core.calendar.models import MarketCalendar
from openticker.storage.sqlite.strategies_repo import insert_strategy
from openticker.use_cases.agents.supervise import start_next_job, watch_jobs
from openticker.use_cases.api_keys import create_api_key, create_review_key, create_script_key
from openticker.use_cases.brain.debrief import start_debrief
from openticker.use_cases.brain.write import create_lesson
from tests.fixtures.brain_day import monday
from tests.fixtures.fake_broker import FakeBrokerPort
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, at
from tests.fixtures.strategies import STRADDLE
from tests.use_cases.agents.test_agent_jobs import SETTINGS, _context, _Events, _Processes


class _Quiet:
    def publish(self, event: object) -> None:
        pass


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


def test_debrief_job_over_mcp_writes_notes_answers_owed_and_is_refused_elsewhere(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A debrief job end to end: the daemon starts it with its own key (the
    harness faked), and the agent's calls over /mcp read the day, write its
    debrief, answer the owed checks, and are refused a trade and another
    day. When the job ends its key stops working."""
    monkeypatch.setattr(registry, "BROKER_REGISTRY", dict(registry.BROKER_REGISTRY))
    registry.register("fake", FakeBrokerPort)
    day = monday()
    after = at(TUESDAY, 16, 0)
    monkeypatch.setattr(mcp_server, "clock", lambda: after)
    lesson = create_lesson(
        "Small edges", "Costs eat them.", [], [], _Quiet(), at(MONDAY, 9, 0), "ui"
    )
    calendar = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())
    start_debrief(MONDAY, SETTINGS, "ui", after, calendar)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, after)
    [launch] = processes.launches
    headers = {"x-api-key": launch.api_key}

    record = json.loads(
        _call(client, headers, "get_day_record", broker="fake", trading_date="2026-09-21")
    )
    owed = record["owed_checks"]
    assert {o["run_id"] or o["order_id"] for o in owed} == {day.run_id, *day.manual_orders}
    written = json.loads(
        _call(
            client,
            headers,
            "write_debrief",
            trading_date="2026-09-21",
            headline="Killed early; the hand trade paid",
            happened="See [[lesson:" + lesson.note.note_id + "]].",
            trade_notes=[{"run_id": day.run_id, "why": "IV rich", "trade_off": "decay"}],
            hindsight=[{"text": "Size down on event days", "knowable_before": True}],
        )
    )
    assert written["updated_by"] == "debrief:2026-09-21" and written["written_by"] == "agent_job"
    for o in owed:
        checked = json.loads(
            _call(
                client,
                headers,
                "check_lesson",
                lesson_id=o["lesson_id"],
                run_id=o["run_id"],
                order_id=o["order_id"],
                outcome="held",
                observed="net under ₹50 after charges",
                why="the edge was smaller than the costs",
            )
        )
        assert checked["check"]["checked_by"] == "debrief:2026-09-21"
    assert checked["lesson"]["status"] == "tested"

    assert "only" in _call(client, headers, "place_order", broker="fake")
    assert "2026-09-21 only" in _call(
        client, headers, "write_debrief", trading_date="2026-09-22", headline="x", happened="y"
    )
    assert "decide" not in _tools(client, headers) and "decide_proposal" not in _tools(
        client, headers
    )
    again = json.loads(
        _call(client, headers, "get_day_record", broker="fake", trading_date="2026-09-21")
    )
    assert again["owed_checks"] == []

    processes.exited[1001] = 0
    watch_jobs(context, at(TUESDAY, 16, 5))
    assert client.post("/mcp", headers={**HEADERS, **headers}, json={}).status_code == 401


def test_review_job_over_mcp_reads_lessons_checks_own_run_and_proposes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review's key reads the lessons about its strategy, answers a check
    on its own run, records the use and raises a proposal, each recorded as
    the review; a check on an order and writes about another strategy are
    refused, over /mcp and REST alike."""
    day = monday()
    other = insert_strategy("Other", STRADDLE, at(MONDAY, 9, 0))
    after = at(TUESDAY, 16, 0)
    monkeypatch.setattr(mcp_server, "clock", lambda: after)
    lesson = create_lesson(
        "Exit before 11:00",
        "Losses after 11:00.",
        [day.strategy_id],
        [],
        _Quiet(),
        at(MONDAY, 9, 0),
        "ui",
    ).note.note_id
    scope = "review:" + day.strategy_id
    headers = {"x-api-key": create_review_key(day.strategy_id, "job_r", after)}

    found = json.loads(
        _call(client, headers, "search_brain", kind="lesson", strategy_id=day.strategy_id)
    )
    assert [n["note_id"] for n in found["notes"]] == [lesson]
    note = json.loads(_call(client, headers, "get_brain_note", note_id=lesson))
    assert [o["run_id"] for o in note["lesson"]["owed"]] == [day.run_id]
    checked = json.loads(
        _call(
            client,
            headers,
            "check_lesson",
            lesson_id=lesson,
            run_id=day.run_id,
            outcome="held",
            observed="flat by 10:55",
            why="killed at 11:00",
        )
    )
    used = json.loads(
        _call(
            client,
            headers,
            "record_lesson_use",
            lesson_id=lesson,
            purpose="review",
            strategy_id=day.strategy_id,
            how="kept the exit",
        )
    )
    raised = json.loads(
        _call(
            client,
            headers,
            "raise_proposal",
            strategy_id=day.strategy_id,
            change="Exit at 10:45 on expiry",
            why=f"[[lesson:{lesson}]] held.",
            wrong_if="One run is a small sample.",
            based_on=[lesson],
        )
    )

    assert checked["check"]["checked_by"] == used["used_by"] == raised["updated_by"] == scope
    assert "checks lessons on the runs" in _call(
        client,
        headers,
        "check_lesson",
        lesson_id=lesson,
        order_id=day.manual_orders[0],
        outcome="held",
        observed="x",
        why="y",
    )
    assert "give strategy_id" in _call(
        client, headers, "record_lesson_use", lesson_id=lesson, purpose="review", how="x"
    )
    assert f"strategy {day.strategy_id} only" in _call(
        client,
        headers,
        "raise_proposal",
        strategy_id=other.id,
        change="x",
        why="y",
        wrong_if="z",
        based_on=[],
    )
    assert "refused" in _call(
        client, headers, "get_day_record", broker="fake", trading_date="2026-09-21"
    )

    rest = {"x-api-key": headers["x-api-key"]}
    proposal = {"strategy_id": other.id, "change": "x", "why": "y", "wrong_if": "z", "based_on": []}
    refused = client.post("/api/v1/brain/proposals", headers=rest, json=proposal)
    order_check = client.post(
        f"/api/v1/brain/lessons/{lesson}/checks",
        headers=rest,
        json={"order_id": day.manual_orders[0], "outcome": "not_tested", "why": "y"},
    )
    no_strategy = client.post(
        f"/api/v1/brain/lessons/{lesson}/uses",
        headers=rest,
        json={"purpose": "review", "how": "x"},
    )
    own = client.post(
        f"/api/v1/brain/lessons/{lesson}/uses",
        headers=rest,
        json={"purpose": "review", "strategy_id": day.strategy_id, "how": "x"},
    )
    assert (refused.status_code, order_check.status_code, no_strategy.status_code) == (
        403,
        403,
        403,
    )
    assert own.status_code == 200 and own.json()["used_by"] == scope
