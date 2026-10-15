"""How the user's coding agent runs, from the web app's Settings (ADR 40)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from openticker.adapters.inbound.rest_api import create_app
from openticker.composition import build_event_bus
from openticker.core.agents.choices import ModelOption
from openticker.core.agents.jobs import Harness
from openticker.events.bus import EventBus
from openticker.ports.agent_job_port import HarnessInfo
from openticker.storage.sqlite.audit_repo import list_audit
from openticker.use_cases.api_keys import create_api_key, create_chat_key

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
ENV = {"OPENTICKER_AGENT_MODEL": "sonnet", "OPENTICKER_AGENT_JOBS_PER_DAY": "7"}


@pytest.fixture
def events() -> Iterator[EventBus]:
    bus = build_event_bus({})
    yield bus
    bus.close()


@pytest.fixture
def client(events: EventBus) -> TestClient:
    key = create_api_key("tests", NOW)[1]
    return TestClient(create_app(events, ENV, clock=lambda: NOW), headers={"X-API-Key": key})


def _folder(body: dict[str, object], kind: str) -> dict[str, dict[str, object]]:
    folders = body["folders"]
    assert isinstance(folders, list)
    return next(f for f in folders if f["kind"] == kind)


def test_settings_show_stored_env_and_resolved(client: TestClient) -> None:
    saved = client.put(
        "/api/v1/agents/settings/folders/reviews",
        json={"model": "opus", "effort": "high", "max_budget_usd": 1, "timeout_minutes": 20},
    )
    assert saved.status_code == 200

    body = client.get("/api/v1/agents/settings").json()

    reviews = _folder(body, "reviews")
    assert reviews["stored"]["model"] == "opus" and reviews["env"]["model"] == "sonnet"
    assert reviews["resolved"] == {
        "harness": "claude",
        "model": "opus",
        "effort": "high",
        "max_budget_usd": 1.0,
        "timeout_minutes": 20,
    }
    assert _folder(body, "general")["resolved"]["model"] == "sonnet"
    assert (body["runs_per_day"], body["runs_per_day_env"]) == (None, 7)


def test_the_managers_check_ins_have_their_own_folder_on_its_harness(client: TestClient) -> None:
    saved = client.put("/api/v1/agents/settings/folders/manager-checks", json={"effort": "low"})
    harness = client.put(
        "/api/v1/agents/settings/folders/manager-checks", json={"harness": "codex"}
    )

    body = client.get("/api/v1/agents/settings").json()

    assert saved.status_code == 200 and harness.status_code == 422
    assert "Manager's harness" in harness.json()["detail"]
    checks = _folder(body, "manager-checks")
    assert checks["stored"]["effort"] == "low" and checks["resolved"]["harness"] == "claude"
    assert _folder(body, "manager")["resolved"]["effort"] != "low"


def test_an_effort_that_isnt_a_level_is_422(client: TestClient) -> None:
    response = client.put("/api/v1/agents/settings/folders/general", json={"effort": "--yolo"})

    assert response.status_code == 422
    assert "isn't an effort level" in response.json()["detail"]


def test_patch_changes_only_what_it_sends_and_delete_resets(client: TestClient) -> None:
    client.patch("/api/v1/agents/settings", json={"runs_per_day": 30})
    body = client.patch("/api/v1/agents/settings", json={"harness": "claude"}).json()
    assert (body["runs_per_day"], body["harness"]) == (30, "claude")
    assert client.patch("/api/v1/agents/settings", json={"runs_per_day": 0}).status_code == 422

    body = client.delete("/api/v1/agents/settings").json()

    assert (body["runs_per_day"], body["harness"]) == (None, None)
    changes = list_audit(10, "AgentSettingsChanged")
    assert {json.loads(e.payload)["change"] for e in changes} == {
        "runs_per_day",
        "harness",
        "reset",
    }


def test_harnesses_say_what_is_installed_with_models_and_efforts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    opus = ModelOption(
        "opus", "Opus 5.5", "For complex work", "claude-opus-5-5", ("low", "high", "max")
    )
    default = ModelOption("default", "Default (recommended)", "Opus 5.5", "claude-opus-5-5")
    found = [
        HarnessInfo(Harness.CLAUDE, True, "2.1.296", (opus,), default),
        HarnessInfo(Harness.CODEX, False),
    ]
    monkeypatch.setattr("openticker.adapters.inbound.rest_api.detect", lambda env: found)

    claude, codex = client.get("/api/v1/agents/harnesses").json()["harnesses"]

    assert (claude["installed"], claude["version"], claude["free_text_model"]) == (
        True,
        "2.1.296",
        False,
    )
    assert claude["models"] == [
        {
            "id": "opus",
            "name": "Opus 5.5",
            "about": "For complex work",
            "resolves_to": "claude-opus-5-5",
            "efforts": ["low", "high", "max"],
            "default_effort": None,
        }
    ]
    assert claude["default_model"]["name"] == "Default (recommended)"
    assert claude["efforts"] == ["low", "high", "max"]  # its models' own, as listed
    assert (codex["installed"], codex["free_text_model"], codex["efforts"]) == (False, True, [])


def test_a_chat_key_cant_read_or_change_settings(client: TestClient) -> None:
    chat = create_chat_key("thr_1", "job_1", NOW)

    for method, path in (
        ("GET", "/api/v1/agents/settings"),
        ("PUT", "/api/v1/agents/settings/folders/general"),
        ("GET", "/api/v1/agents/harnesses"),
    ):
        response = client.request(method, path, json={}, headers={"X-API-Key": chat})
        assert response.status_code == 403, path
