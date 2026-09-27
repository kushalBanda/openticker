"""What the web app's end-to-end tests do from outside the server: another
process sharing its home, as an agent's stdio MCP server is. Its events
reach the server only through the audit log.

    uv run python -m tests.fixtures.e2e_agent --home <dir> order
    uv run python -m tests.fixtures.e2e_agent --home <dir> kill
    uv run python -m tests.fixtures.e2e_agent --home <dir> end-runs
    uv run python -m tests.fixtures.e2e_agent --home <dir> later

`order`: Claude Code buys 5 TCS through the MCP tools, as an in-memory MCP
client named "Claude Code" (the stdio transport is the only difference).
`kill`: SBIN mean reversion hits its daily loss limit, as the daemon's
runner reports it.
`end-runs`: every running strategy run ends, as the daemon's runner ends one
after a stop.
`later`: 15 minutes pass on the shared clock, so a browser's next request
starts a new visit (ADR 31); the unused sign-in links are made again.
"""

import argparse
import asyncio
import os
from dataclasses import replace
from pathlib import Path

from mcp.client import Client
from mcp.types import Implementation

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.composition import build_event_bus
from openticker.core.strategies.runs import RunStatus
from openticker.events.types import StrategyStopped
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.strategies_repo import list_strategies
from openticker.use_cases.web_sessions import create_sign_in_link
from tests.fixtures.e2e_server import CLOCK_FILE, E2E_ENV, Clock, E2EBroker


async def _order() -> None:
    info = Implementation(name="Claude Code", version="2.1.0")
    async with Client(mcp_server.mcp, client_info=info) as client:
        arguments = {
            "broker": "fake",
            "symbol": "TCS",
            "exchange": "NSE",
            "side": "BUY",
            "quantity": 5,
            "product": "MIS",
        }
        result = await client.call_tool("place_order", arguments)
        if result.is_error:
            raise SystemExit(f"place_order failed: {result.content}")


def _kill(home: Path) -> None:
    [strategy] = [s for s in list_strategies() if s.name == "SBIN mean reversion"]
    events = build_event_bus({})
    events.publish(
        StrategyStopped(
            strategy_id=strategy.id,
            run_id="e2e",
            name=strategy.name,
            reason="daily_loss_limit",
            detail="daily loss limit ₹2,000 reached; closed 150 SBIN at 812.40",
            realized_pnl=-2014.5,
            occurred_at=Clock(home)(),  # the server's time, as the daemon stamps it
        )
    )
    events.close()


def _end_runs() -> None:
    for run in runs_repo.active_runs():
        runs_repo.save_run(replace(run, status=RunStatus.ENDED))


def _later(home: Path) -> None:
    anchor = home / CLOCK_FILE
    anchor.write_text(repr(float(anchor.read_text()) - 15 * 60))
    # The server's links last 10 minutes: the tests get fresh ones, made now.
    links = home / "links.txt"
    old = links.read_text().split()
    base = old[0].split("/login")[0]
    now = Clock(home)()
    links.write_text("\n".join(create_sign_in_link(base, now) for _ in old) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("what", choices=["order", "kill", "end-runs", "later"])
    args = parser.parse_args()
    os.environ["OPENTICKER_HOME"] = args.home
    os.environ.update(E2E_ENV)
    registry.register("fake", E2EBroker)
    mcp_server.clock = Clock(Path(args.home))  # the server's time: the market is open
    if args.what == "order":
        asyncio.run(_order())
    elif args.what == "kill":
        _kill(Path(args.home))
    elif args.what == "end-runs":
        _end_runs()
    else:
        _later(Path(args.home))


if __name__ == "__main__":
    main()
