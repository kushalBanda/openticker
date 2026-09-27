"""The Agents page's route (ADR 29 and ADR 35 in docs/adr)."""

from datetime import timedelta

import pytest

from openticker.storage.sqlite.agent_clients_repo import note_client
from openticker.use_cases import agent_clients
from tests.adapters.inbound.web.conftest import NOW, Web


@pytest.fixture(autouse=True)
def _fresh_notes() -> None:
    agent_clients.forget_noted()


def test_agents_lists_clients_with_todays_calls_and_the_review_settings(web: Web) -> None:
    note_client("codex", "stdio", "0.9", 7, NOW - timedelta(days=1), "place_order")
    note_client("claude-code", "stdio", "2.1", 3, NOW, "get_positions")
    note_client("claude-code", "stdio", "2.1", 2, NOW + timedelta(minutes=1), "get_quote")

    body = web.sign_in().get("/api/v1/agents").json()

    assert [(c["name"], c["calls"], c["calls_today"], c["last_tool"]) for c in body["clients"]] == [
        ("claude-code", 5, 5, "get_quote"),
        ("codex", 7, 0, "place_order"),  # seen yesterday: nothing today
    ]
    assert body["clients"][0]["last_seen_at"] == "2026-09-22T09:31:00+05:30"
    assert (body["harness"], body["started_today"]) == ("claude", 0)
    assert body["jobs_per_day"] >= 1 and body["timeout_minutes"] >= 1


def test_a_new_day_starts_the_days_count_again() -> None:
    note_client("codex", "stdio", None, 4, NOW, "get_quote")
    note_client("codex", "stdio", None, 1, NOW + timedelta(days=1), None)

    [client] = agent_clients.get_agent_clients(NOW + timedelta(days=1))

    assert (client.calls, client.calls_today, client.last_tool) == (5, 1, "get_quote")
