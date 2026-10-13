"""The models each harness offers, read from what the harness itself prints
(ADR 40 in docs/adr). Nothing is listed here: Claude Code and Codex ship
new models often, and each knows its own, and which the user's account may
use. Pure: adapters/agents/harness.py runs the commands.

- Claude Code answers an `initialize` control request on its stream-json
  input with the models its /model picker shows: alias or full name, a
  display name, a description and the full name an alias runs today.
- Codex prints its model catalog with `codex debug models`; the ones it
  shows in its own picker have visibility "list", best first by priority.
"""

import json
from collections.abc import Iterable
from typing import Any

from openticker.core.agents.choices import ModelOption

# Sent on Claude Code's stdin; its answer carries the same request_id.
CLAUDE_REQUEST_ID = "openticker-models"
CLAUDE_INITIALIZE = json.dumps(
    {
        "type": "control_request",
        "request_id": CLAUDE_REQUEST_ID,
        "request": {"subtype": "initialize"},
    }
)
CLAUDE_DEFAULT = "default"  # the entry for "no model named", not a model


def claude_models(lines: Iterable[str]) -> tuple[tuple[ModelOption, ...], ModelOption | None]:
    """The models in Claude Code's answer to `initialize`, and the one it
    runs when none is named. ((), None) when there's no answer."""
    for line in lines:
        message = _json(line)
        if message.get("type") != "control_response":
            continue
        response = message.get("response")
        if not isinstance(response, dict) or response.get("request_id") != CLAUDE_REQUEST_ID:
            continue
        answer = response.get("response")
        entries = answer.get("models") if isinstance(answer, dict) else None
        options = [_claude_option(entry) for entry in entries or []]
        found = [option for option in options if option is not None]
        default = next((o for o in found if o.id == CLAUDE_DEFAULT), None)
        return tuple(o for o in found if o.id != CLAUDE_DEFAULT), default
    return (), None


def codex_models(text: str) -> tuple[ModelOption, ...]:
    """The models Codex shows in its own picker, best first. () when the
    catalog can't be read."""
    catalog = _json(text)
    entries = catalog.get("models")
    if not isinstance(entries, list):
        return ()
    shown = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("visibility") == "list"
        and isinstance(entry.get("slug"), str)
    ]
    shown.sort(key=lambda entry: _number(entry.get("priority")))
    return tuple(
        ModelOption(
            id=entry["slug"],
            name=_text(entry.get("display_name")) or entry["slug"],
            about=_text(entry.get("description")),
        )
        for entry in shown
    )


def _claude_option(entry: Any) -> ModelOption | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("value"), str):
        return None
    value = entry["value"]
    resolved = _text(entry.get("resolvedModel")) or None
    return ModelOption(
        id=value,
        name=_text(entry.get("displayName")) or value,
        about=_text(entry.get("description")),
        resolves_to=resolved if resolved != value else None,
    )


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) else float("inf")
