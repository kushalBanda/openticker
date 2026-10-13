import json

from openticker.core.agents.catalog import (
    CLAUDE_INITIALIZE,
    CLAUDE_REQUEST_ID,
    claude_models,
    codex_models,
    configured_default,
)
from openticker.core.agents.choices import ModelOption


def _answer(models: list[dict[str, object]], request_id: str = CLAUDE_REQUEST_ID) -> str:
    return json.dumps(
        {
            "type": "control_response",
            "response": {"request_id": request_id, "response": {"models": models}},
        }
    )


def test_claude_lists_what_its_picker_shows_with_the_default_apart() -> None:
    lines = [
        '{"type":"system","subtype":"hook_started"}',
        "not json",
        _answer([], request_id="someone-else"),
        _answer(
            [
                {
                    "value": "default",
                    "displayName": "Default (recommended)",
                    "description": "Opus 5.5 · Best for everyday, complex tasks",
                    "resolvedModel": "claude-opus-5-5",
                },
                {
                    "value": "opus",
                    "displayName": "Opus 5.5",
                    "description": "For complex work and everyday tasks",
                    "resolvedModel": "claude-opus-5-5",
                },
                {"value": "claude-opus-4-8", "displayName": "Opus 4.8", "description": "Older"},
                {"displayName": "no value: left out"},
            ]
        ),
    ]

    models, default = claude_models(lines)

    assert models == (
        ModelOption("opus", "Opus 5.5", "For complex work and everyday tasks", "claude-opus-5-5"),
        ModelOption("claude-opus-4-8", "Opus 4.8", "Older"),
    )
    assert default is not None and default.resolves_to == "claude-opus-5-5"
    assert claude_models(["{}"]) == ((), None)  # no answer: any name is typed
    assert json.loads(CLAUDE_INITIALIZE)["request"] == {"subtype": "initialize"}


def test_codex_lists_its_pickers_models_best_first() -> None:
    text = json.dumps(
        {
            "models": [
                {"slug": "old", "display_name": "Old", "visibility": "list", "priority": 9},
                {"slug": "hidden", "visibility": "hide", "priority": 1},
                {
                    "slug": "gpt-6-luna",
                    "display_name": "GPT-6-Luna",
                    "description": "Fast and affordable.",
                    "visibility": "list",
                    "priority": 4,
                },
            ]
        }
    )

    assert codex_models(text) == (
        ModelOption("gpt-6-luna", "GPT-6-Luna", "Fast and affordable."),
        ModelOption("old", "Old", ""),
    )
    assert codex_models("error: not signed in") == ()


def test_a_default_set_in_the_users_settings_shows_as_its_listed_model() -> None:
    opus = ModelOption("opus", "Opus 5.5", "For complex work", "claude-opus-5-5")
    why = "Set in your Claude Code settings"

    assert configured_default("opus", (opus,), why) == ModelOption(
        "opus", "Opus 5.5", "Opus 5.5 · Set in your Claude Code settings", "claude-opus-5-5"
    )
    assert configured_default("claude-opus-5-5", (opus,), why).name == "Opus 5.5"
    assert configured_default("my-model", (opus,), why).about == f"my-model · {why}"
