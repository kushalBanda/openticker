"""A stand-in for Codex in the web app's end-to-end tests (ADR 40): run as
`codex exec --json ... [resume <id>] <prompt>`, it prints a short turn in
Codex's `exec --json` event format (tests/fixtures/transcripts/), a line at a
time, and answers by repeating the message it read on stdin. With `resume`
it keeps that session and says so, so a test can see a chat continue."""

import json
import sys
import time
import uuid

PAUSE = 0.3  # between lines, so a page can watch the steps arrive


def _emit(event: dict[str, object]) -> None:
    print(json.dumps(event), flush=True)
    time.sleep(PAUSE)


def main() -> None:
    argv = sys.argv[1:]
    if argv == ["--version"]:
        print("codex-cli 0.48.0")
        return
    message = sys.stdin.read().strip()
    resumed = argv[argv.index("resume") + 1] if "resume" in argv else None
    session = resumed or str(uuid.uuid4())
    answer = f"You asked: {message}" + (f" (resumed {session[:8]})" if resumed else "")
    _emit({"type": "thread.started", "thread_id": session})
    _emit({"type": "turn.started"})
    _emit(
        {
            "type": "item.completed",
            "item": {"id": "item_0", "type": "reasoning", "text": "Look at the desk first."},
        }
    )
    call = {
        "id": "item_1",
        "type": "mcp_tool_call",
        "server": "openticker_job",
        "tool": "list_strategies",
        "arguments": {},
    }
    _emit({"type": "item.started", "item": {**call, "status": "in_progress"}})
    result = {"content": [{"type": "text", "text": "3 strategies"}]}
    _emit({"type": "item.completed", "item": {**call, "result": result, "status": "completed"}})
    _emit(
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "agent_message", "text": answer},
        }
    )
    usage = {"input_tokens": 2400, "cached_input_tokens": 2000, "output_tokens": 180}
    _emit({"type": "turn.completed", "usage": usage})


if __name__ == "__main__":
    main()
