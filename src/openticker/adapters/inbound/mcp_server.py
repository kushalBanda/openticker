"""MCP server — tool registrations, each a thin call into use_cases. Every
tool reaches its broker through the registry (`get_adapter`); none knows a
broker by name. Tool design conventions: ADR 8 in docs/adr.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from importlib.metadata import version
from typing import Annotated

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from openticker.adapters.brokers.registry import (
    BROKER_REGISTRY,
    BrokerConfigError,
    UnknownBrokerError,
    get_adapter,
    get_login_url,
)
from openticker.adapters.inbound.mcp_models import (
    BarResult,
    BarsResult,
    ConnectResult,
    InstrumentResult,
    LoginUrlResult,
    QuoteResult,
    SearchResult,
    SyncResult,
)
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, InstrumentType, Interval
from openticker.use_cases.connect_broker import connect_broker as connect_broker_use_case
from openticker.use_cases.get_historical_bars import (
    get_historical_bars as get_historical_bars_use_case,
)
from openticker.use_cases.get_quote import get_quote as get_quote_use_case
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from openticker.use_cases.search_instruments import (
    search_instruments as search_instruments_use_case,
)
from openticker.use_cases.sync_instruments import sync_instruments as sync_instruments_use_case

INSTRUCTIONS = """\
OpenTicker: Indian market data through a connected broker.

Typical flow:
1. get_broker_login_url -> the user logs in -> connect_broker with the request_token
   from the redirect. Broker sessions expire daily; any tool failing with a
   "reconnect" error means repeat this step.
2. sync_instruments once per day (instrument lists change with every expiry).
3. search_instruments to find the exact symbol, then get_quote / get_historical_bars.

Symbols are OpenTicker's own, not the broker's: RELIANCE, NIFTY 50,
NIFTY29SEP26FUT, NIFTY22SEP2623350CE (<name><DDMMMYY><strike><CE|PE>).
Dates are exchange-local trading dates; returned times carry the +05:30 offset.
"""

mcp = MCPServer(
    name="openticker",
    title="OpenTicker",
    version=version("openticker"),
    instructions=INSTRUCTIONS,
)

DEFAULT_MAX_BARS = 200
DEFAULT_SEARCH_LIMIT = 20

Broker = Annotated[
    str,
    Field(description=f"Broker name. Registered: {', '.join(sorted(BROKER_REGISTRY))}."),
]
Symbol = Annotated[
    str,
    Field(
        description="Standardized symbol, e.g. RELIANCE, NIFTY 50, NIFTY22SEP2623350CE. "
        "Use search_instruments to find one."
    ),
]
ExchangeParam = Annotated[
    Exchange, Field(description="NSE/BSE: cash and indices. NFO/BFO: F&O. MCX: commodities.")
]

# Failures the agent can act on (reconnect, fix the symbol, sync, set config).
# The SDK withholds any other exception's text from the client as a crash, so
# these are re-raised as ToolError to reach the agent with their message
# (ADR 7 in docs/adr).
_AGENT_FIXABLE_ERRORS = (
    BrokerError,
    UnknownInstrumentError,
    UnknownBrokerError,
    BrokerConfigError,
)


@contextmanager
def _agent_facing_errors() -> Iterator[None]:
    try:
        yield
    except _AGENT_FIXABLE_ERRORS as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    title="Get broker login URL",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_broker_login_url(broker: Broker) -> LoginUrlResult:
    """Step 1 of connecting a broker: a URL for the user to open and log in on
    the broker's own page. Show it to the user; don't open it yourself."""
    with _agent_facing_errors():
        url = get_login_url(broker)
    return LoginUrlResult(
        broker=broker,
        login_url=url,
        next_step="After login the browser lands on a URL with a `request_token` query "
        "parameter; ask the user for it and call connect_broker.",
    )


@mcp.tool(
    title="Connect broker",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
def connect_broker(
    broker: Broker,
    request_token: Annotated[
        str,
        Field(description="From the redirect URL after login. Single-use, valid for minutes."),
    ],
) -> ConnectResult:
    """Step 2 of connecting a broker: exchange the login's request_token for a
    session, stored encrypted and replacing any previous one. The session
    token itself is never returned."""
    with _agent_facing_errors():
        connect_broker_use_case(get_adapter(broker), request_token)
    return ConnectResult(
        broker=broker,
        connected=True,
        next_step="Call sync_instruments if it hasn't run today.",
    )


@mcp.tool(
    title="Sync instrument master",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
    ),
)
def sync_instruments(broker: Broker) -> SyncResult:
    """Download the broker's full instrument list into the local master that
    symbol lookups use. Run once a day, and whenever a symbol isn't found.
    Takes a few seconds; safe to re-run."""
    with _agent_facing_errors():
        count = sync_instruments_use_case(get_adapter(broker))
    return SyncResult(broker=broker, instrument_count=count)


@mcp.tool(
    title="Search instruments",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def search_instruments(
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="Part of a symbol, case-insensitive: RELIANCE, NIFTY 50, "
            "NIFTY22SEP26 (all NIFTY contracts expiring 22 Sep 2026), BANKNIFTY29SEP26FUT.",
        ),
    ],
    exchange: Annotated[Exchange | None, Field(description="Only this exchange.")] = None,
    instrument_type: Annotated[
        InstrumentType | None, Field(description="Only this type, e.g. CE for call options.")
    ] = None,
    include_expired: Annotated[
        bool, Field(description="Include contracts past expiry.")
    ] = False,
    limit: Annotated[int, Field(ge=1, le=500, description="Most results to return.")] = (
        DEFAULT_SEARCH_LIMIT
    ),
) -> SearchResult:
    """Find instruments in the local master by symbol fragment — exact match
    first, then prefix matches. Reads local data only (run sync_instruments
    first if nothing is found)."""
    found = search_instruments_use_case(
        query,
        exchange,
        instrument_type,
        include_expired,
        today=datetime.now(EXCHANGE_TIMEZONE).date(),
        limit=limit + 1,
    )
    return SearchResult(
        instruments=[InstrumentResult.of(instrument) for instrument in found[:limit]],
        truncated=len(found) > limit,
    )


@mcp.tool(
    title="Get quote",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def get_quote(broker: Broker, symbol: Symbol, exchange: ExchangeParam) -> QuoteResult:
    """Last traded price of one instrument, live from the broker."""
    with _agent_facing_errors():
        quote = get_quote_use_case(get_adapter(broker), symbol, exchange.value)
    return QuoteResult.of(quote)


@mcp.tool(
    title="Get historical bars",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
    ),
)
def get_historical_bars(
    broker: Broker,
    symbol: Symbol,
    exchange: ExchangeParam,
    interval: Annotated[
        Interval, Field(description="Candle size. `day` for anything longer than a few weeks.")
    ],
    start_date: Annotated[date, Field(description="First trading date, inclusive.")],
    end_date: Annotated[date, Field(description="Last trading date, inclusive.")],
    max_bars: Annotated[
        int,
        Field(ge=1, le=5000, description="Most recent bars to return inline; all are stored."),
    ] = DEFAULT_MAX_BARS,
) -> BarsResult:
    """OHLCV candles fetched from the broker and stored locally. Minute data
    for long ranges is large: prefer a coarser interval or a shorter range."""
    with _agent_facing_errors():
        bars = get_historical_bars_use_case(
            get_adapter(broker), symbol, exchange.value, interval.value, start_date, end_date
        )
    returned = bars[-max_bars:]
    return BarsResult(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        total_bars=len(bars),
        bars=[BarResult.of(bar) for bar in returned],
        note=(
            f"Returned the last {len(returned)} of {len(bars)} bars. Narrow the date "
            "range, use a coarser interval, or raise max_bars."
            if len(returned) < len(bars)
            else None
        ),
    )


def main() -> None:
    load_dotenv()  # process entry point only — importing this module must stay side-effect-free
    mcp.run()


if __name__ == "__main__":
    main()
