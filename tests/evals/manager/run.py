"""Runs the desk manager's evals (ADR 44 in docs/adr): each scenario's desk
in a fresh OPENTICKER_HOME, served over MCP as openticker-serve serves it,
and one manager turn by the real harness in labs/, then graded on the desk
it leaves. Costs real money: see README.md.

    uv run python -m tests.evals.manager.run --harness claude --model haiku
    uv run python -m tests.evals.manager.run --model sonnet --scenario own_stop_acted --repeat 3
"""

import argparse
import os
import socket
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import uvicorn

from openticker.adapters.agents.harness import HarnessProcesses
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.mcp_scoped import MCP_PATH, WithMcp
from openticker.adapters.inbound.rest_api import create_app
from openticker.core.agents.choices import FolderKind, RunChoice
from openticker.core.agents.jobs import AgentJob, AgentSettings, Harness
from openticker.core.agents.transcript import StepKind, read_outcome, read_steps
from openticker.storage import agent_job_files
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import agent_jobs_repo
from openticker.use_cases.agents.manager import get_manager, queue_due_manager_wake
from openticker.use_cases.agents.supervise import (
    AgentContext,
    start_next_chat_turn,
    watch_jobs,
)
from openticker.use_cases.strategies.board import strategy_board
from tests.evals.manager.desk import EvalClock, EvalDesk
from tests.evals.manager.scenarios import SCENARIOS, EvalResult, Scenario

LABS = Path(__file__).resolve().parents[3] / "labs"
STARTING_CAPITAL = 2_000_000.0
ENV = {"SANDBOX_STARTING_CAPITAL": f"{STARTING_CAPITAL:.0f}"}
TURN_LIMIT = timedelta(minutes=15)


@dataclass(frozen=True)
class Choice:
    harness: Harness
    model: str | None
    effort: str | None
    budget: float | None


@dataclass(frozen=True)
class Graded:
    scenario: str
    failures: list[str]
    result: EvalResult | None  # None: the turn didn't finish
    seconds: float


def run(scenario: Scenario, choice: Choice, show_wake: bool = False) -> Graded:
    home = Path(tempfile.mkdtemp(prefix=f"openticker-eval-{scenario.name}-"))
    os.environ["OPENTICKER_HOME"] = str(home)
    clock = EvalClock(scenario.clock)
    desk = EvalDesk(clock)
    port = _free_port()
    context = AgentContext(
        HarnessProcesses(),
        desk.events,
        _settings(choice),
        LABS,
        f"http://127.0.0.1:{port}{MCP_PATH}",
    )
    scenario.seed(desk, context)
    server = _serve(desk, clock, port)
    started = time.monotonic()
    try:
        clock.set(scenario.clock)
        clock.run()
        job = queue_due_manager_wake(context, clock())
        expected = f"manager-wake:{scenario.reason.value}"
        if job is None or job.trigger != expected:
            got = None if job is None else job.trigger
            return Graded(scenario.name, [f"seeded wrong: {got}, not {expected}"], None, 0.0)
        if show_wake:
            print(f"--- {scenario.name}: {job.trigger}\n{job.prompt}\n")
            return Graded(scenario.name, [], None, 0.0)
        print(f"  {scenario.name}: {scenario.summary}; turn {job.id} running…", flush=True)
        ended = _turn(context, desk, job)
        seconds = time.monotonic() - started
        if ended is None:
            return Graded(scenario.name, ["the turn didn't end in time"], None, seconds)
        result = _result(ended, context, clock)
        failures = list(scenario.grade(result))
        if ended.end_reason is not None and ended.end_reason.value != "finished":
            failures.insert(0, f"the turn ended {ended.end_reason.value}: {ended.end_detail}")
        return Graded(scenario.name, failures, result, seconds)
    finally:
        server.should_exit = True


def _settings(choice: Choice) -> AgentSettings:
    run_choice = RunChoice(choice.harness, choice.model, choice.effort, choice.budget)
    return AgentSettings(
        harness=choice.harness,
        timeout=TURN_LIMIT,
        jobs_per_day=40,
        choices={FolderKind.MANAGER: run_choice, FolderKind.MANAGER_CHECKS: run_choice},
    )


def _serve(desk: EvalDesk, clock: EvalClock, port: int) -> uvicorn.Server:
    mcp_server.clock = clock
    mcp_server.use_event_bus(desk.events)
    app = WithMcp(create_app(desk.events, ENV, clock=clock), mcp_server.mcp)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def _turn(context: AgentContext, desk: EvalDesk, job: AgentJob) -> AgentJob | None:
    """Drives the daemon's chat lane until the turn ends."""
    deadline = time.monotonic() + TURN_LIMIT.total_seconds() + 60
    while time.monotonic() < deadline:
        now = desk.clock()
        watch_jobs(context, now)
        start_next_chat_turn(context, now)
        desk.step()
        found = agent_jobs_repo.find_job(job.id)
        if found is not None and found.ended_at is not None:
            return found
        time.sleep(1.0)
    return None


def _result(job: AgentJob, context: AgentContext, clock: EvalClock) -> EvalResult:
    events = agent_job_files.events_path(job.id)
    lines = events.read_text().splitlines() if events.exists() else []
    steps = read_steps(job.harness, lines)
    outcome = read_outcome(job.harness, lines)
    now = clock()
    view = get_manager(STARTING_CAPITAL, load_calendar(), now)
    board = strategy_board(load_calendar(), now)
    after = queue_due_manager_wake(context, now + timedelta(minutes=1))
    return EvalResult(
        answer=outcome.answer or "",
        tools=[s.tool for s in steps if s.kind is StepKind.TOOL and s.tool],
        lines={str(v.line.key): v for v in view.lines},
        board={row.strategy.name: row for row in board},
        undone=view.undone,
        next_wake=None if after is None else after.trigger.removeprefix("manager-wake:"),
        cost_usd=outcome.cost_usd if outcome.cost_usd is not None else job.cost_usd,
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _report(graded: Graded) -> None:
    mark = "PASS" if not graded.failures else "FAIL"
    result = graded.result
    cost = "" if result is None or result.cost_usd is None else f", ${result.cost_usd:.3f}"
    print(f"{mark} {graded.scenario} ({graded.seconds:.0f}s{cost})")
    for failure in graded.failures:
        print(f"    - {failure}")
    if result is not None:
        print(f"    tools: {', '.join(result.tools) or 'none'}")
        print("    answer: " + result.answer.replace("\n", "\n            "))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--harness", choices=[h.value for h in Harness], default="claude")
    parser.add_argument("--model", help="as the harness takes it: haiku, sonnet, opus, …")
    parser.add_argument("--effort", help="an effort level the harness offers")
    parser.add_argument("--budget", type=float, default=2.0, help="USD per turn (Claude Code)")
    parser.add_argument("--scenario", choices=[s.name for s in SCENARIOS], action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--show-wake", action="store_true", help="seed and print each wake; run no harness"
    )
    args = parser.parse_args()
    choice = Choice(Harness(args.harness), args.model, args.effort, args.budget)
    picked = [s for s in SCENARIOS if not args.scenario or s.name in args.scenario]
    print(f"{choice.harness.value} {choice.model or '(default model)'} {choice.effort or ''}")
    if args.show_wake:
        for scenario in picked:
            run(scenario, choice, show_wake=True)
        return
    graded = [run(s, choice) for _ in range(args.repeat) for s in picked]
    for one in graded:
        _report(one)
    passed = sum(not g.failures for g in graded)
    spent = sum(g.result.cost_usd or 0.0 for g in graded if g.result is not None)
    print(f"{passed}/{len(graded)} passed, ${spent:.2f}")
    sys.exit(0 if passed == len(graded) else 1)


if __name__ == "__main__":
    main()
