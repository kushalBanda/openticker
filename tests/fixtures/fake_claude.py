"""A stand-in for Claude Code in the web app's end-to-end tests (ADR 40): run
as `claude -p ... --output-format stream-json`, it prints a short turn in
Claude Code's own event format (tests/fixtures/transcripts/), a line at a
time, and answers by repeating the message it read on stdin; as the
reviewer (`--agent reviewer`, asked on the command line) it answers with a
verdict. With `--resume` it keeps that session and says so, so a test can
see a chat continue. A message with "slowly" in it takes its time, a step every 1.5 seconds and
twenty of them, so a test can watch steps arrive and stop it. Its failures:
resuming a session whose id starts "gone-", a model it doesn't know, and a
message asking it to use up its "spend cap". A message asking for a
"paper order" places one, a resting limit buy of TCS, with the turn's own key,
as the real agent would through OpenTicker's tools."""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

PAUSE = 0.3  # between lines, so a page can watch the steps arrive


def _flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _emit(event: dict[str, object], pause: float = PAUSE) -> None:
    if event["type"] in ("assistant", "user"):
        event["timestamp"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(json.dumps(event), flush=True)
    time.sleep(pause)


def _say(base: dict[str, object], *content: dict[str, object], pause: float = PAUSE) -> None:
    _emit({**base, "type": "assistant", "message": {"content": list(content)}}, pause)


def _fail(session: str, text: str | None, subtype: str = "success") -> None:
    """Ends the turn as Claude Code does when it can't go on: an error result."""
    _emit({"type": "system", "subtype": "init", "session_id": session, "model": "claude-opus-5-5"})
    result: dict[str, object] = {"type": "result", "subtype": subtype, "is_error": True}
    _emit({**result, "session_id": session, **({"result": text} if text else {})})
    sys.exit(1)


def _place_order(argv: list[str]) -> tuple[str, bool]:
    """A resting paper order through the REST API, as the turn's key allows."""
    servers = json.loads(_flag(argv, "--mcp-config") or "{}")["mcpServers"]["openticker"]
    base = servers["url"].removesuffix("/mcp")
    body = {
        "broker": "fake",
        "symbol": "TCS",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 1,
        "product": "CNC",
        "order_type": "LIMIT",
        "price": 3000,
    }
    request = urllib.request.Request(
        f"{base}/api/v1/orders",
        data=json.dumps(body).encode(),
        headers={"X-API-Key": os.environ["OPENTICKER_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return str(json.loads(response.read())["order_id"]), False
    except urllib.error.HTTPError as refused:  # the key's scope said no, as a ToolError would
        return str(json.loads(refused.read())["detail"]), True


def main() -> None:
    argv = sys.argv[1:]
    if argv == ["--version"]:
        print("2.1.296 (Claude Code)")
        return
    # A review or debrief is asked on the command line; a chat's message comes on stdin.
    agent = _flag(argv, "--agent")
    message = argv[argv.index("-p") + 1] if agent else sys.stdin.read().strip()
    resumed = _flag(argv, "--resume")
    session = resumed or str(uuid.uuid4())
    model = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}.get(
        _flag(argv, "--model") or "", "claude-opus-5-5"
    )
    asked_model = _flag(argv, "--model")
    if resumed and resumed.startswith("gone-"):  # a session Claude Code no longer has
        _fail(session, f"No conversation found with session ID: {resumed}")
    if asked_model and asked_model not in ("opus", "sonnet", "haiku", "fable"):
        _fail(
            session,
            f"There's an issue with the selected model ({asked_model}). It may not exist "
            "or you may not have access to it.",
        )
    if "spend cap" in message:
        _fail(session, None, subtype="error_max_budget_usd")
    pause = 1.5 if "slowly" in message else PAUSE
    if agent == "reviewer":
        answer = "keep: net after charges holds up over its runs."
    else:
        answer = f"You asked: {message}" + (f" (resumed {session[:8]})" if resumed else "")
    base: dict[str, object] = {"session_id": session, "parent_tool_use_id": None}
    _emit({"type": "system", "subtype": "init", "session_id": session, "model": model})
    _say(base, {"type": "thinking", "thinking": "Look at the desk first."})
    call = {"type": "tool_use", "id": "toolu_1", "name": "mcp__openticker__list_strategies"}
    _say(base, {**call, "input": {}})
    result = {"type": "tool_result", "tool_use_id": "toolu_1", "content": "3 strategies"}
    _emit({**base, "type": "user", "message": {"content": [result]}}, pause)
    if "paper order" in message:
        order = {"type": "tool_use", "id": "toolu_o", "name": "mcp__openticker__place_order"}
        _say(base, {**order, "input": {"symbol": "TCS", "side": "BUY", "quantity": 1}})
        content, refused = _place_order(argv)
        placed = {
            "type": "tool_result",
            "tool_use_id": "toolu_o",
            "content": content,
            "is_error": refused,
        }
        _emit({**base, "type": "user", "message": {"content": [placed]}})
    if pause > PAUSE:
        for n in range(1, 21):
            quote = {"type": "tool_use", "id": f"toolu_q{n}", "name": "mcp__openticker__get_quote"}
            _say(base, {**quote, "input": {"symbol": f"STEP{n}"}}, pause=pause)
    _say(base, {"type": "text", "text": answer})
    usage = {"inputTokens": 1200, "outputTokens": 300}
    _emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": answer,
            "session_id": session,
            "duration_ms": 1800,
            "total_cost_usd": 0.0123,
            "modelUsage": {model: {**usage, "cacheReadInputTokens": 0}},
        }
    )


if __name__ == "__main__":
    main()
