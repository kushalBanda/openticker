"""`openticker-serve`: the long-running server (ADR 12 in docs/adr), and the
commands that manage its API keys (ADR 17 in docs/adr).

    openticker-serve                     run the REST API, live prices, sandbox execution
                                         and strategies
    openticker-serve keys create <name>  print a new key, once
    openticker-serve keys list
    openticker-serve keys revoke <name>
"""

import argparse
import ipaddress
import logging
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import partial

import uvicorn
from dotenv import load_dotenv

from openticker.adapters.brokers.registry import FEED_REGISTRY, get_feed
from openticker.adapters.inbound.daemon.execution_loop import ExecutionLoop
from openticker.adapters.inbound.daemon.feed_loop import FeedLoop
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.strategy_loop import StrategyLoop
from openticker.adapters.inbound.rest_api import API_KEY_HEADER, create_app
from openticker.composition import (
    build_event_bus,
    capital_cap,
    order_broker,
    price_timeouts,
    watch_list,
)
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError
from openticker.use_cases.api_keys import (
    InvalidApiKeyNameError,
    create_api_key,
    get_api_keys,
    revoke,
)
from openticker.use_cases.watched_instruments import watched_instruments

DEFAULT_BIND = "127.0.0.1:8750"


class BindConfigError(Exception):
    pass


def parse_bind(env: Mapping[str, str]) -> tuple[str, int]:
    """`OPENTICKER_BIND` as host:port; an IPv6 host in brackets, [::1]:8750."""
    raw = env.get("OPENTICKER_BIND") or DEFAULT_BIND
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise BindConfigError(f"OPENTICKER_BIND must be host:port, got {raw!r}")
    return host.removeprefix("[").removesuffix("]"), int(port)


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
    commands = parser.add_subparsers(dest="command")
    keys = commands.add_parser("keys", help="manage REST API keys").add_subparsers(
        dest="action", required=True
    )
    keys.add_parser("create", help="create a key and print it once").add_argument("name")
    keys.add_parser("list", help="list keys (never the keys themselves)")
    keys.add_parser("revoke", help="revoke a key by name").add_argument("name")
    args = parser.parse_args(argv)

    if args.command == "keys":
        sys.exit(_keys(args.action, getattr(args, "name", None)))
    _serve(os.environ)


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


def _serve(env: Mapping[str, str]) -> None:
    host, port = parse_bind(env)
    if not is_loopback(host):
        print(
            f"warning: listening on {host}, reachable beyond this machine; every route "
            "except /health still needs an API key",
            file=sys.stderr,
        )
    if not any(stored.revoked_at is None for stored in get_api_keys()):
        print(
            "no API keys yet: every request will be refused until you run "
            "`openticker-serve keys create <name>`",
            file=sys.stderr,
        )
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    watch = watch_list(env)
    events = build_event_bus(env)  # now, so bad notification settings fail at startup
    prices = LatestPrices()
    stop = threading.Event()
    feeds = [
        threading.Thread(
            target=FeedLoop(
                broker,
                partial(get_feed, broker),
                partial(watched_instruments, watch),
                prices,
                events,
            ).run,
            args=(stop,),
            name=f"feed-{broker}",
        )
        for broker in FEED_REGISTRY
    ]
    feeds += [
        threading.Thread(
            target=ExecutionLoop(
                partial(order_broker, broker, env), prices, events, load_calendar
            ).run,
            args=(stop,),
            name=f"execution-{broker}",
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
    for thread in feeds:
        thread.start()
    try:
        uvicorn.run(create_app(events, env), host=host, port=port)
    finally:
        stop.set()
        for thread in feeds:
            thread.join(timeout=10)
        events.close()


if __name__ == "__main__":
    main()
