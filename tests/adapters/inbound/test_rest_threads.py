"""The web app's chats over REST (ADR 40): web-only routes, each message an
agent job the daemon runs."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from openticker.adapters.inbound.rest_api import create_app
from openticker.composition import build_event_bus
from openticker.core.agents.jobs import AgentJobEndReason
from openticker.events.bus import EventBus
from openticker.storage.sqlite import agent_jobs_repo
from openticker.storage.sqlite.audit_repo import write_audit
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.api_keys import create_api_key, create_chat_key
from openticker.use_cases.strategies.define import create_strategy
from tests.fixtures.strategies import STRADDLE, list_nifty_market

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


@pytest.fixture
def events() -> Iterator[EventBus]:
    bus = build_event_bus({})
    yield bus
    bus.close()


@pytest.fixture
def client(events: EventBus) -> TestClient:
    key = create_api_key("tests", NOW)[1]
    return TestClient(create_app(events, {}, clock=lambda: NOW), headers={"X-API-Key": key})


def test_start_chat_returns_the_thread_with_its_waiting_turn(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agent-threads",
        json={"message": "Why did expiry days lose?", "model": "opus", "effort": "high"},
    )

    assert response.status_code == 202
    body = response.json()
    assert (body["title"], body["folder"], body["harness"]) == (
        "Why did expiry days lose?",
        "general",
        "claude",
    )
    [turn] = body["turns"]
    assert turn["job"]["status"] == "pending"
    assert (turn["job"]["prompt"], turn["job"]["model"], turn["job"]["effort"]) == (
        "Why did expiry days lose?",
        "opus",
        "high",
    )
    assert not body["continuable"]
    listed = client.get("/api/v1/agent-threads").json()["threads"]
    assert [t["thread_id"] for t in listed] == [body["thread_id"]]
    assert client.get(f"/api/v1/agent-threads/{body['thread_id']}").json()["turns"] == [turn]


def test_one_message_waits_and_can_be_edited_or_taken_back_until_it_starts(
    client: TestClient,
) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()
    thread_id, job_id = body["thread_id"], body["turns"][0]["job"]["job_id"]
    messages = f"/api/v1/agent-threads/{thread_id}/messages"

    full = client.post(messages, json={"message": "?"})
    edited = client.patch(f"{messages}/{job_id}", json={"message": "hello"})
    removed = client.delete(f"{messages}/{job_id}")

    assert full.status_code == 409 and "edit it" in full.json()["detail"]
    assert edited.status_code == 200 and edited.json()["job"]["prompt"] == "hello"
    assert removed.status_code == 200 and removed.json()["end_reason"] == "stopped"
    late = client.patch(f"{messages}/{job_id}", json={"message": "again"})
    assert late.status_code == 409 and "already took" in late.json()["detail"]
    assert client.delete(f"{messages}/job_nope").status_code == 404
    assert client.patch(f"{messages}/{job_id}", json={"message": ""}).status_code == 422


def test_a_chat_whose_first_turn_never_ran_is_409(client: TestClient) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()
    with write_transaction() as session:
        agent_jobs_repo.end_job(
            session, body["turns"][0]["job"]["job_id"], AgentJobEndReason.START_FAILED, "x", NOW
        )

    response = client.post(
        f"/api/v1/agent-threads/{body['thread_id']}/messages", json={"message": "?"}
    )

    assert response.status_code == 409 and "start a new chat" in response.json()["detail"]


def test_bad_effort_is_422_and_an_unknown_chat_404(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/agent-threads", json={"message": "hi", "effort": "minimal"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/agent-threads", json={"message": "hi", "effort": "ludicrous"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/agent-threads/thr_nope").status_code == 404


def test_a_chats_own_key_cannot_start_or_steer_chats(events: EventBus) -> None:
    key = create_chat_key("thr_1", "job_1", NOW)
    chat = TestClient(create_app(events, {}, clock=lambda: NOW), headers={"X-API-Key": key})

    assert chat.post("/api/v1/agent-threads", json={"message": "hi"}).status_code == 403
    assert chat.get("/api/v1/agent-threads").status_code == 403


def test_stop_a_chats_waiting_message_then_nothing_to_stop(client: TestClient) -> None:
    thread_id = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()["thread_id"]

    stopped = client.post(f"/api/v1/agent-threads/{thread_id}/stop")
    again = client.post(f"/api/v1/agent-threads/{thread_id}/stop")

    assert stopped.status_code == 200 and stopped.json()["end_reason"] == "stopped"
    assert again.status_code == 409


def test_a_folder_lists_its_chats_and_the_counts_come_with_every_list(
    client: TestClient,
) -> None:
    list_nifty_market()
    strategy_id = create_strategy("straddle", STRADDLE, NOW).id
    review = client.post(f"/api/v1/strategies/{strategy_id}/review").json()["job"]
    client.post("/api/v1/agent-threads", json={"message": "Hi"})

    body = client.get(
        "/api/v1/agent-threads", params={"folder": "strategy", "subject": strategy_id}
    ).json()

    [listed] = body["threads"]
    assert (listed["thread_id"], listed["folder"], listed["title"]) == (
        review["thread_id"],
        "review",
        "Review of straddle",
    )
    assert sorted((c["folder"], c["subject_name"], c["threads"]) for c in body["counts"]) == [
        ("general", None, 1),
        ("review", None, 1),
        ("strategy", "straddle", 1),
    ]
    assert client.get("/api/v1/agent-threads", params={"limit": 0}).status_code == 422


def test_delete_a_chat_once_the_agent_is_off_it_and_both_are_audited(client: TestClient) -> None:
    thread_id = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()["thread_id"]

    busy = client.delete(f"/api/v1/agent-threads/{thread_id}")
    client.post(f"/api/v1/agent-threads/{thread_id}/stop")
    deleted = client.delete(f"/api/v1/agent-threads/{thread_id}")

    assert busy.status_code == 409
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/agent-threads/{thread_id}").status_code == 404
    assert client.get("/api/v1/agent-threads").json()["threads"] == []
    assert client.delete(f"/api/v1/agent-threads/{thread_id}").status_code == 404
    entries = client.get("/api/v1/audit").json()["entries"]
    kinds = {e["event_type"]: e for e in entries}
    assert kinds["AgentChatStarted"]["details"]["title"] == "hi"
    assert kinds["AgentChatDeleted"]["details"]["thread_id"] == thread_id


def test_a_pinned_chat_is_listed_apart_from_recents_until_unpinned(client: TestClient) -> None:
    first = client.post("/api/v1/agent-threads", json={"message": "first"}).json()["thread_id"]
    second = client.post("/api/v1/agent-threads", json={"message": "second"}).json()["thread_id"]

    pinned = client.patch(f"/api/v1/agent-threads/{first}", json={"pinned": True})

    assert pinned.status_code == 200
    assert (pinned.json()["thread_id"], pinned.json()["pinned"]) == (first, True)
    listed = client.get("/api/v1/agent-threads").json()
    assert [t["thread_id"] for t in listed["pinned"]] == [first]
    assert [t["thread_id"] for t in listed["threads"]] == [second]
    assert client.get(f"/api/v1/agent-threads/{first}").json()["pinned"] is True

    client.patch(f"/api/v1/agent-threads/{first}", json={"pinned": False})
    listed = client.get("/api/v1/agent-threads").json()
    assert listed["pinned"] == []
    assert {t["thread_id"] for t in listed["threads"]} == {first, second}


def test_pinning_an_unknown_chat_is_404(client: TestClient) -> None:
    assert client.patch("/api/v1/agent-threads/thr_nope", json={"pinned": True}).status_code == 404


def test_rename_and_archive_over_rest_and_their_refusals(client: TestClient) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()
    thread_id = body["thread_id"]

    busy = client.patch(f"/api/v1/agent-threads/{thread_id}", json={"archived": True})
    blank = client.patch(f"/api/v1/agent-threads/{thread_id}", json={"title": ""})
    renamed = client.patch(f"/api/v1/agent-threads/{thread_id}", json={"title": "Hedges"})

    assert busy.status_code == 409
    assert blank.status_code == 422
    assert renamed.json()["title"] == "Hedges"
    with write_transaction() as session:
        agent_jobs_repo.end_job(
            session,
            body["turns"][0]["job"]["job_id"],
            AgentJobEndReason.FAILED,
            "x",
            NOW + timedelta(minutes=1),
        )
    archived = client.patch(f"/api/v1/agent-threads/{thread_id}", json={"archived": True}).json()
    assert (archived["archived"], archived["failed"], archived["unread"]) == (True, True, True)
    assert client.get("/api/v1/agent-threads").json()["threads"] == []


def test_search_over_rest_is_its_own_route_not_a_chat_id(client: TestClient) -> None:
    thread_id = client.post("/api/v1/agent-threads", json={"message": "Hedge my NIFTY"}).json()[
        "thread_id"
    ]

    found = client.get("/api/v1/agent-threads/search", params={"q": "nifty"})
    short = client.get("/api/v1/agent-threads/search", params={"q": "n"})
    reviews = client.get("/api/v1/agent-threads/search", params={"q": "nifty", "kind": "reviews"})

    assert found.status_code == 200
    [hit] = found.json()["hits"]
    assert (hit["thread"]["thread_id"], hit["matched"], hit["snippet"]) == (
        thread_id,
        "message",
        "Hedge my NIFTY",
    )
    assert short.status_code == 422
    assert reviews.json()["hits"] == []


def test_a_chats_changes_over_rest(client: TestClient) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "Hedge it"}).json()
    write_audit("OrderPlaced", NOW, f"chat:claude:{body['thread_id']}", '{"order_id": "o1"}')

    changes = client.get(f"/api/v1/agent-threads/{body['thread_id']}/changes")
    unknown = client.get("/api/v1/agent-threads/thr_nope/changes")

    [entry] = changes.json()["entries"]
    assert (entry["event_type"], entry["details"], entry["source"]) == (
        "OrderPlaced",
        {"order_id": "o1"},
        "agent",
    )
    assert unknown.status_code == 404


def test_a_chat_keys_rest_call_is_recorded_as_its_chat_with_its_harness(
    client: TestClient, events: EventBus
) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "hi"}).json()
    key = create_chat_key(body["thread_id"], body["turns"][0]["job"]["job_id"], NOW)
    as_chat = TestClient(create_app(events, {}, clock=lambda: NOW), headers={"X-API-Key": key})

    made = as_chat.post("/api/v1/watchlists", json={"name": "From a chat"})

    assert made.status_code == 200
    [entry] = client.get(f"/api/v1/agent-threads/{body['thread_id']}/changes").json()["entries"]
    assert (entry["event_type"], entry["triggered_by"]) == (
        "WatchlistChanged",
        f"chat:claude:{body['thread_id']}",
    )


def test_a_read_only_chat_says_so_and_its_key_reads_but_places_nothing(
    client: TestClient, events: EventBus
) -> None:
    body = client.post("/api/v1/agent-threads", json={"message": "hi", "access": "read"}).json()
    key = create_chat_key(body["thread_id"], "job_1", NOW, read_only=True)
    as_chat = TestClient(create_app(events, {}, clock=lambda: NOW), headers={"X-API-Key": key})

    refused = as_chat.post("/api/v1/watchlists", json={"name": "From a chat"})

    assert body["access"] == "read"
    assert client.get("/api/v1/agent-threads").json()["threads"][0]["access"] == "read"
    assert refused.status_code == 403 and "read-only" in refused.json()["detail"]
    assert as_chat.get("/api/v1/watchlists").status_code == 200
    assert (
        client.post("/api/v1/agent-threads", json={"message": "x", "access": "x"}).status_code
        == 422
    )
