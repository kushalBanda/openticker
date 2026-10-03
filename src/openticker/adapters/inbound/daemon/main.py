"""`openticker-serve`: the long-running server (ADR 12 in docs/adr), and the
commands that manage its API keys (ADR 17 in docs/adr) and sign in to its
web app (ADR 31).

    openticker-serve                     run the web app, the REST API, live prices,
                                         sandbox execution, strategies, hosted scripts,
                                         agent jobs, the daily charge-rate check, and
                                         MCP at /mcp
    openticker-serve --dev               the same, for the web app's Vite dev server
    openticker-serve --no-browser        the same, without opening the web app
    openticker-serve keys create <name>  print a new key, once
    openticker-serve keys list
    openticker-serve keys revoke <name>
    openticker-serve ui login            print a new sign-in link for the web app
"""

import argparse
import copy
import ipaddress
import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv

from openticker.adapters.agents.harness import HarnessProcesses
from openticker.adapters.brokers.registry import FEED_REGISTRY, get_adapter, get_feed
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.daemon.agent_loop import AgentLoop
from openticker.adapters.inbound.daemon.charge_check_loop import ChargeCheckLoop
from openticker.adapters.inbound.daemon.execution_loop import ExecutionLoop
from openticker.adapters.inbound.daemon.feed_loop import FeedLoop
from openticker.adapters.inbound.daemon.pnl_loop import PnlLoop
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.script_loop import ScriptLoop
from openticker.adapters.inbound.daemon.strategy_loop import StrategyLoop
from openticker.adapters.inbound.mcp_scoped import MCP_PATH, WithMcp
from openticker.adapters.inbound.rest_api import HideAlertTokens, create_app
from openticker.adapters.inbound.web.app import DIST
from openticker.adapters.inbound.web.auth import API_KEY_HEADER, WebSettings
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.adapters.scripts.supervisor import ProcessSupervisor
from openticker.composition import (
    AgentConfigError,
    agent_settings,
    build_event_bus,
    capital_cap,
    labs_dir,
    order_broker,
    price_timeouts,
    sandbox_settings,
    script_limits,
    watch_list,
)
from openticker.events.types import BrokerConnected, BrokerDisconnected
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, Quote
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError
from openticker.use_cases.agents.supervise import AgentContext
from openticker.use_cases.api_keys import (
    InvalidApiKeyNameError,
    create_api_key,
    get_api_keys,
    revoke,
)
from openticker.use_cases.feed_status import FeedStatus, feed_status
from openticker.use_cases.watched_instruments import watched_instruments
from openticker.use_cases.web_sessions import create_sign_in_link

DEFAULT_BIND = "127.0.0.1:8750"
DEV_ORIGIN = "http://localhost:5173"  # Vite's; OPENTICKER_UI_ORIGIN overrides it


class BindConfigError(Exception):
    pass


def parse_bind(env: Mapping[str, str]) -> tuple[str, int]:
    """`OPENTICKER_BIND` as host:port; an IPv6 host in brackets, [::1]:8750."""
    raw = env.get("OPENTICKER_BIND") or DEFAULT_BIND
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise BindConfigError(f"OPENTICKER_BIND must be host:port, got {raw!r}")
    return host.removeprefix("[").removesuffix("]"), int(port)


def local_url(host: str, port: int) -> str:
    """Where a process on this machine reaches the server: a wildcard bind
    is reached through loopback."""
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def web_settings(
    host: str, port: int, dev: bool, env: Mapping[str, str], dist: Path = DIST
) -> WebSettings:
    """With `dev`, the Vite dev server's pages may call this server too."""
    dev_origin = (env.get("OPENTICKER_UI_ORIGIN") or DEV_ORIGIN) if dev else None
    return WebSettings(local_url(host, port), port, dev_origin, dist)


def _sign_in_link(web: WebSettings) -> str:
    """A link through the dev server when there is one: its page is the one to open."""
    return create_sign_in_link(web.dev_origin or web.own_origin, datetime.now(UTC))


def open_when_up(
    link: str,
    health: str,
    stop: threading.Event,
    opener: Callable[[str], object] = webbrowser.open,
    timeout: float = 30,
) -> None:
    """Opens the sign-in link once the server answers, so the page does not
    load before the server can serve it."""
    deadline = time.monotonic() + timeout
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            if httpx.get(health, timeout=1).is_success:
                opener(link)
                return
        except httpx.TransportError:
            pass
        stop.wait(0.2)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> None:
    load_dotenv()  # process entry point only; importing this module must stay side-effect-free
    run(sys.argv[1:])


def run(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="openticker-serve", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dev", action="store_true", help="also accept the web app's Vite dev server"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="don't open the web app in a browser"
    )
    commands = parser.add_subparsers(dest="command")
    keys = commands.add_parser("keys", help="manage REST API keys").add_subparsers(
        dest="action", required=True
    )
    keys.add_parser("create", help="create a key and print it once").add_argument("name")
    keys.add_parser("list", help="list keys (never the keys themselves)")
    keys.add_parser("revoke", help="revoke a key by name").add_argument("name")
    ui = commands.add_parser("ui", help="the web app").add_subparsers(dest="action", required=True)
    ui.add_parser("login", help="print a new sign-in link, valid once for 10 minutes")
    args = parser.parse_args(argv)

    if args.command == "keys":
        sys.exit(_keys(args.action, getattr(args, "name", None)))
    if args.command == "ui":
        sys.exit(_ui_login(os.environ, args.dev))
    _serve(os.environ, args.dev, browser=not args.no_browser and sys.stdout.isatty())


def _ui_login(env: Mapping[str, str], dev: bool) -> int:
    host, port = parse_bind(env)
    print(_sign_in_link(web_settings(host, port, dev, env)))
    print("Open it in a browser on this machine: it works once, for 10 minutes.", file=sys.stderr)
    return 0


def _keys(action: str, name: str | None) -> int:
    now = datetime.now(UTC)
    if action == "create":
        assert name is not None
        try:
            stored, key = create_api_key(name, now)
        except (InvalidApiKeyNameError, DuplicateApiKeyNameError) as exc:
            print(exc, file=sys.stderr)
            return 1
        print(key)
        print(
            f"Key {stored.name!r} created. It is shown only this once: send it in the "
            f"{API_KEY_HEADER} header.",
            file=sys.stderr,
        )
        return 0
    if action == "list":
        for stored in get_api_keys():
            created = stored.created_at.astimezone(EXCHANGE_TIMEZONE).strftime("%Y-%m-%d %H:%M")
            state = (
                f"revoked {stored.revoked_at.astimezone(EXCHANGE_TIMEZONE):%Y-%m-%d %H:%M}"
                if stored.revoked_at
                else "active"
            )
            print(f"{stored.name}\t{stored.prefix}...\t{stored.scope}\tcreated {created}\t{state}")
        return 0
    assert name is not None
    if not revoke(name, now):
        print(f"no active API key named {name!r}", file=sys.stderr)
        return 1
    print(f"Key {name!r} revoked.", file=sys.stderr)
    return 0


def _serve(env: Mapping[str, str], dev: bool = False, browser: bool = False) -> None:
    """With `browser`, the web app opens in this machine's browser once the server is up."""
    host, port = parse_bind(env)
    if not is_loopback(host):
        print(
            f"warning: listening on {host}, reachable beyond this machine; every route "
            "except /health still needs an API key",
            file=sys.stderr,
        )
    if not any(stored.revoked_at is None for stored in get_api_keys()):
        print(
            "no API keys yet: REST clients need one from `openticker-serve keys create <name>`; "
            "the web app signs in with the link below",
            file=sys.stderr,
        )
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    watch = watch_list(env)
    events = build_event_bus(env)  # now, so bad notification settings fail at startup
    limits = script_limits(env)  # likewise bad script limits
    agents = agent_settings(env)  # and bad agent job settings
    mcp_server.use_event_bus(events)  # MCP over HTTP publishes on this server's bus
    prices = LatestPrices()
    stop = threading.Event()
    wake = threading.Event()  # a page opened in the web app wants new prices now
    web = web_settings(host, port, dev, env)
    hub = StreamHub(
        prices,
        partial(_quotes, _PRICE_BROKER),
        partial(_feed_status, _PRICE_BROKER, prices),
        wake,
        partial(datetime.now, UTC),
    )
    feed_loops = {
        broker: FeedLoop(
            broker,
            partial(get_feed, broker),
            partial(watched_instruments, watch, browser=hub.watched),
            prices,
            events,
            wake=wake,
        )
        for broker in FEED_REGISTRY
    }

    def reopen_feed(event: BrokerConnected | BrokerDisconnected) -> None:
        if (loop := feed_loops.get(event.broker)) is not None:
            loop.reopen()

    events.subscribe(BrokerConnected, reopen_feed)
    events.subscribe(BrokerDisconnected, reopen_feed)
    feeds = [
        threading.Thread(target=loop.run, args=(stop,), name=f"feed-{broker}")
        for broker, loop in feed_loops.items()
    ]
    feeds += [
        threading.Thread(
            target=ExecutionLoop(
                partial(order_broker, broker, env),
                prices,
                events,
                load_calendar,
                fills=sandbox_settings(env).fills,
            ).run,
            args=(stop,),
            name=f"execution-{broker}",
        )
        for broker in FEED_REGISTRY
    ]
    feeds.append(
        threading.Thread(
            target=PnlLoop(partial(order_broker, _PRICE_BROKER, env), load_calendar).run,
            args=(stop,),
            name="pnl",
        )
    )
    feeds += [
        threading.Thread(
            target=ChargeCheckLoop(broker, partial(get_adapter, broker), events).run,
            args=(stop,),
            name=f"charge-check-{broker}",
        )
        for broker in FEED_REGISTRY
    ]
    feeds.append(
        threading.Thread(
            target=StrategyLoop(
                partial(order_broker, env=env),
                prices,
                events,
                load_calendar,
                capital_cap(env),
                timeouts=price_timeouts(env),
            ).run,
            args=(stop,),
            name="strategies",
        )
    )
    feeds.append(
        threading.Thread(
            target=ScriptLoop(
                ProcessSupervisor(), events, load_calendar, limits, local_url(host, port)
            ).run,
            args=(stop,),
            name="scripts",
        )
    )
    try:
        agent_context = AgentContext(
            HarnessProcesses(), events, agents, labs_dir(env), local_url(host, port) + MCP_PATH
        )
    except AgentConfigError as exc:
        print(f"warning: agent jobs won't run: {exc}", file=sys.stderr)
    else:
        feeds.append(
            threading.Thread(target=AgentLoop(agent_context).run, args=(stop,), name="agents")
        )
    for thread in feeds:
        thread.start()
    link = _sign_in_link(web)
    print(f"\nOpenTicker: {link}\n", flush=True)
    if browser:
        threading.Thread(
            target=open_when_up,
            args=(link, local_url(host, port) + "/health", stop),
            name="open-browser",
            daemon=True,
        ).start()
    # uvicorn raises SIGTERM again once it has shut down. With the default
    # handler that ends the process at once, before the loops are stopped
    # below, and hosted scripts would be left running with nothing watching.
    signal.signal(signal.SIGTERM, exit_on_signal)
    try:
        uvicorn.run(
            WithMcp(create_app(events, env, hub=hub, web=web), mcp_server.mcp),
            host=host,
            port=port,
            log_config=_log_config(),
        )
    finally:
        stop.set()
        for thread in feeds:
            thread.join(timeout=10)
        events.close()


# The broker whose prices the web app shows: the only one with a live feed.
_PRICE_BROKER = next(iter(FEED_REGISTRY))


def _quotes(broker: str, instruments: Sequence[Instrument]) -> list[Quote]:
    return get_adapter(broker).get_quotes(list(instruments))


def _feed_status(broker: str, prices: LatestPrices) -> FeedStatus:
    return feed_status(broker, prices.last_streamed_at(), datetime.now(UTC))


def exit_on_signal(signum: int, frame: object) -> None:
    """Exits the way a signal would (128 + its number), but through the
    `finally` blocks on the way out."""
    raise SystemExit(128 + signum)


def _log_config() -> dict[str, Any]:
    """uvicorn's own logging, with alert URL tokens kept out of the access log."""
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    config.setdefault("filters", {})["hide_alert_tokens"] = {"()": HideAlertTokens}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).append("hide_alert_tokens")
    return config


if __name__ == "__main__":
    main()
