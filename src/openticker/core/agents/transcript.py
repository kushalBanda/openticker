"""One turn of the user's coding agent, as steps (ADR 40 in docs/adr): what
it said, thought, called and changed on the way to its answer, and what ran
(the session, the model, tokens, cost, how long). Read from the event stream
the harness prints on stdout, one JSON object a line. Pure.

Claude Code's `--output-format stream-json --verbose`: `system` lines (`init`
names the session and model), `assistant` lines whose content blocks are
`text`, `thinking` and `tool_use`, `user` lines carrying each `tool_result`,
and a closing `result` line with the answer, cost, tokens and duration. Its
`--output-format json` prints only that `result` line, which reads the same.

Codex's `exec --json`: `thread.started` (its `thread_id` is the session),
`item.started`, `item.updated` and `item.completed` for each item (an
`agent_message`, `reasoning`, a `command_execution`, a `file_change`, an
`mcp_tool_call`, a `web_search`, a `todo_list`, an `error`), then
`turn.completed` with its usage, or `turn.failed`; `error` for a stream
error. It names no model and no cost, and its lines carry no time.

A line that isn't JSON, or isn't an event this knows, is skipped: the stream
is read while it is still being written, so its last line may be partial.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from openticker.core.agents.jobs import Harness

# A tool's result is cut to this many characters (ADR 8 in docs/adr).
MAX_RESULT_CHARS = 2_000
MAX_SUMMARY_CHARS = 120

_OPENTICKER_TOOL = "mcp__openticker__"
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
# The input that says most about a call, in the order looked for.
_MAIN_INPUTS = ("file_path", "path", "pattern", "query", "command", "url", "description")


class StepKind(StrEnum):
    TEXT = "text"  # what the agent wrote
    THINKING = "thinking"
    TOOL = "tool"  # a tool call and its result
    EDIT = "edit"  # a file it changed
    ERROR = "error"


@dataclass(frozen=True)
class Step:
    kind: StepKind
    at: datetime | None = None  # when the harness says
    text: str | None = None  # TEXT, THINKING, ERROR
    tool: str | None = None  # "get_strategy_ledger" (OpenTicker's prefix dropped), "Edit"
    summary: str | None = None  # one line: the call's main input
    result: str | None = None  # cut to MAX_RESULT_CHARS
    failed: bool = False


@dataclass(frozen=True)
class TurnOutcome:
    answer: str | None = None  # the final assistant text
    session_id: str | None = None  # the harness's own, to resume the conversation
    model_used: str | None = None  # the model that did most of the work
    input_tokens: int | None = None  # cached input included
    output_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None  # why the harness says the turn failed


def read_steps(harness: Harness, lines: Iterable[str]) -> list[Step]:
    if harness is Harness.CODEX:
        return _codex_steps(lines)
    steps: list[Step] = []
    tools: dict[str, int] = {}  # a tool_use id: its step's index
    for event in _events(lines):
        kind = event.get("type")
        if event.get("parent_tool_use_id"):
            continue  # a subagent's own work, inside the call that started it
        at = _time(event.get("timestamp"))
        if kind == "assistant":
            for block in _blocks(event):
                step = _assistant_step(block, at)
                if step is None:
                    continue
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    tools[block["id"]] = len(steps)
                steps.append(step)
        elif kind == "user":
            for block in _blocks(event):
                index = tools.get(block.get("tool_use_id", ""))
                if block.get("type") == "tool_result" and index is not None:
                    steps[index] = replace(
                        steps[index],
                        result=_cut(_result_text(block.get("content")), MAX_RESULT_CHARS),
                        failed=bool(block.get("is_error")),
                    )
        elif kind == "result":
            error = _error_of(event)
            if error is not None:
                steps.append(Step(StepKind.ERROR, at, text=error))
    return steps


def read_outcome(harness: Harness, lines: Iterable[str]) -> TurnOutcome:
    if harness is Harness.CODEX:
        return _codex_outcome(lines)
    outcome = TurnOutcome()
    last_text: str | None = None
    init_model: str | None = None
    for event in _events(lines):
        kind = event.get("type")
        session = event.get("session_id")
        if isinstance(session, str) and session:
            outcome = replace(outcome, session_id=session)
        if kind == "system" and event.get("subtype") == "init":
            init_model = _str(event.get("model"))
        elif kind == "assistant" and not event.get("parent_tool_use_id"):
            texts = [b["text"] for b in _blocks(event) if b.get("type") == "text" and b.get("text")]
            if texts:
                last_text = "\n\n".join(texts)
        elif kind == "result":
            outcome = _result_outcome(event, outcome)
    return replace(
        outcome,
        answer=outcome.answer or last_text,
        model_used=outcome.model_used or init_model,
    )


def _result_outcome(event: Mapping[str, Any], outcome: TurnOutcome) -> TurnOutcome:
    model_used, input_tokens, output_tokens = _usage(event)
    cost = event.get("total_cost_usd")
    duration = event.get("duration_ms")
    answer = event.get("result")
    error = _error_of(event)
    return replace(
        outcome,
        answer=answer if isinstance(answer, str) and answer.strip() and error is None else None,
        model_used=model_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        duration_ms=int(duration) if isinstance(duration, int | float) else None,
        error=error,
    )


def _usage(event: Mapping[str, Any]) -> tuple[str | None, int | None, int | None]:
    """The model with the most output tokens (Claude Code also asks a small
    model for side tasks), and the turn's tokens over every model."""
    by_model = event.get("modelUsage")
    if isinstance(by_model, dict) and by_model:
        models = {name: used for name, used in by_model.items() if isinstance(used, dict)}
        main = max(models, key=lambda name: _int(models[name].get("outputTokens")), default=None)
        inputs = sum(
            _int(used.get(field))
            for used in models.values()
            for field in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
        )
        outputs = sum(_int(used.get("outputTokens")) for used in models.values())
        return main, inputs, outputs
    usage = event.get("usage")
    if isinstance(usage, dict):
        inputs = sum(
            _int(usage.get(field))
            for field in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        return None, inputs, _int(usage.get("output_tokens"))
    return None, None, None


def _error_of(event: Mapping[str, Any]) -> str | None:
    subtype = event.get("subtype")
    if subtype == "success" and not event.get("is_error"):
        return None
    result = event.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(subtype, str) and subtype.startswith("error_"):
        reason = subtype.removeprefix("error_")
        return _CLAUDE_ERRORS.get(reason, reason.replace("_", " "))
    return "the agent reported an error"


# Claude Code's error results, said as what happened.
_CLAUDE_ERRORS = {
    "max_budget_usd": "it reached its spend cap and stopped",
    "max_turns": "it reached its turn limit and stopped",
    "during_execution": "it failed while working",
}
# What a harness says when the conversation it was asked to resume is gone.
_SESSION_GONE = re.compile(
    r"no conversation found|(session|thread|rollout)\b[^.\n]{0,40}\bnot found", re.IGNORECASE
)


def session_gone(error: str | None) -> bool:
    """True when a turn failed because its conversation can't be resumed."""
    return error is not None and _SESSION_GONE.search(error) is not None


def _assistant_step(block: Mapping[str, Any], at: datetime | None) -> Step | None:
    kind = block.get("type")
    if kind == "text" and _str(block.get("text")):
        return Step(StepKind.TEXT, at, text=block["text"])
    if kind == "thinking" and _str(block.get("thinking")):
        return Step(StepKind.THINKING, at, text=block["thinking"])
    if kind == "tool_use" and _str(block.get("name")):
        name: str = block["name"]
        given = block.get("input")
        arguments: dict[str, Any] = given if isinstance(given, dict) else {}
        tool = name.removeprefix(_OPENTICKER_TOOL)
        edit = name in _EDIT_TOOLS
        return Step(
            StepKind.EDIT if edit else StepKind.TOOL,
            at,
            tool=tool,
            summary=_summary(arguments, edit),
        )
    return None


def _summary(arguments: Mapping[str, Any], edit: bool) -> str | None:
    for name in _MAIN_INPUTS:
        value = arguments.get(name)
        if isinstance(value, str) and value:
            if edit:
                added = arguments.get("new_string") or arguments.get("content")
                if isinstance(added, str) and added:
                    value += f" · +{added.count(chr(10)) + 1} lines"
            return _cut(value, MAX_SUMMARY_CHARS)
    shown = ", ".join(f"{k}={_brief(v)}" for k, v in arguments.items())
    return _cut(shown, MAX_SUMMARY_CHARS) if shown else None


def _brief(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


def _events(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _blocks(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _codex_steps(lines: Iterable[str]) -> list[Step]:
    """Each item once, as it was last reported: a command shows while it
    runs and gains its output when it completes."""
    steps: list[Step] = []
    items: dict[str, int] = {}  # an item's id: its step's index
    for event in _events(lines):
        kind = event.get("type")
        if kind in ("item.started", "item.updated", "item.completed"):
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            step = _codex_step(item)
            if step is None:
                continue
            key = item.get("id")
            index = items.get(key) if isinstance(key, str) else None
            if index is None:
                if isinstance(key, str):
                    items[key] = len(steps)
                steps.append(step)
            else:
                steps[index] = step
        elif kind in ("turn.failed", "error"):
            steps.append(Step(StepKind.ERROR, text=_codex_error(event)))
    return steps


def _codex_step(item: Mapping[str, Any]) -> Step | None:
    kind = item.get("type")
    failed = item.get("status") in ("failed", "declined")
    if kind == "agent_message" and _str(item.get("text")):
        return Step(StepKind.TEXT, text=item["text"])
    if kind == "reasoning" and _str(item.get("text")):
        return Step(StepKind.THINKING, text=item["text"])
    if kind == "command_execution":
        output = item.get("aggregated_output")
        code = item.get("exit_code")
        return Step(
            StepKind.TOOL,
            tool="shell",
            summary=_cut(_str(item.get("command")) or "", MAX_SUMMARY_CHARS) or None,
            result=_cut(output, MAX_RESULT_CHARS) if isinstance(output, str) and output else None,
            failed=failed or (isinstance(code, int) and code != 0),
        )
    if kind == "mcp_tool_call" and _str(item.get("tool")):
        given = item.get("arguments")
        arguments: dict[str, Any] = given if isinstance(given, dict) else {}
        error = item.get("error")
        return Step(
            StepKind.TOOL,
            tool=item["tool"],
            summary=_summary(arguments, edit=False),
            result=_cut(_codex_result(item.get("result")), MAX_RESULT_CHARS) or None,
            failed=failed or isinstance(error, dict),
        )
    if kind == "file_change":
        changes = item.get("changes")
        paths = [
            f"{change.get('path')} ({change.get('kind', 'update')})"
            for change in (changes if isinstance(changes, list) else [])
            if isinstance(change, dict) and _str(change.get("path"))
        ]
        return Step(
            StepKind.EDIT,
            tool="edit",
            summary=_cut(", ".join(paths), MAX_SUMMARY_CHARS) or None,
            failed=failed,
        )
    if kind == "web_search" and _str(item.get("query")):
        return Step(
            StepKind.TOOL, tool="web_search", summary=_cut(item["query"], MAX_SUMMARY_CHARS)
        )
    if kind == "error" and _str(item.get("message")):
        return Step(StepKind.ERROR, text=item["message"])
    return None  # a todo list, or a kind this doesn't know


def _codex_result(result: object) -> str:
    """An MCP call's result: its content's text parts."""
    if isinstance(result, dict):
        return _result_text(result.get("content"))
    return result if isinstance(result, str) else ""


def _codex_error(event: Mapping[str, Any]) -> str:
    error = event.get("error")
    message = error.get("message") if isinstance(error, dict) else event.get("message")
    return (
        message.strip()
        if isinstance(message, str) and message.strip()
        else "the agent reported an error"
    )


def _codex_outcome(lines: Iterable[str]) -> TurnOutcome:
    outcome = TurnOutcome()
    inputs = outputs = 0
    counted = False
    for event in _events(lines):
        kind = event.get("type")
        if kind == "thread.started" and _str(event.get("thread_id")):
            outcome = replace(outcome, session_id=event["thread_id"])
        elif kind == "item.completed":
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and _str(item.get("text"))
            ):
                outcome = replace(outcome, answer=item["text"])
        elif kind == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                counted = True
                # Its input takes in the cached input, and its output the
                # reasoning, as OpenAI's usage counts them.
                inputs += _int(usage.get("input_tokens"))
                outputs += _int(usage.get("output_tokens"))
        elif kind in ("turn.failed", "error"):
            outcome = replace(outcome, error=_codex_error(event))
    return replace(
        outcome,
        input_tokens=inputs if counted else None,
        output_tokens=outputs if counted else None,
    )
