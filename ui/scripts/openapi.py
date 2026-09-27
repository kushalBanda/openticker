"""Prints openticker-serve's OpenAPI schema, web routes included, for
`pnpm gen:api`. Contributor tooling: nothing here runs in the server."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.web.auth import WebSettings
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.composition import build_event_bus
from openticker.use_cases.feed_status import FeedStatus


def _status() -> FeedStatus:
    return FeedStatus("zerodha", False, None, None, False, "no-broker")


events = build_event_bus({})
hub = StreamHub(LatestPrices(), lambda _: [], _status, threading.Event(), lambda: datetime.now(UTC))
web = WebSettings("http://127.0.0.1:8750", 8750, None, Path("dist"))
print(json.dumps(create_app(events, {}, hub=hub, web=web).openapi(), indent=2))
events.close()
