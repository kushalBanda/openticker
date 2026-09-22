"""MCP server — tool registrations, each a thin call into use_cases. Every
tool reaches its broker through the registry (`get_adapter`); none knows a
broker by name. Tool design conventions: ADR 8 in docs/adr.
"""

import atexit
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
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
    AuditLogResult,
    BarsResult,
    ConnectResult,
    FundsResult,
    LoginUrlResult,
    MarketStatusesResult,
    MarketStatusResult,
    OptionChainResult,
    OrderbookResult,
    PlaceOrderResult,
    PositionsResult,
    QuoteResult,
    RiskCheckResult,
    SearchResult,
    SyncResult,
)
from openticker.composition import (
    SandboxConfigError,
    build_event_bus,
    capital_cap,
    order_broker,
)
from openticker.core.calendar.calendar import CalendarError
from openticker.core.options.underlyings import UnsupportedUnderlyingError
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.events.bus import EventBus
from openticker.events.types import (
    BrokerSessionExpired,
    InstrumentSyncCompleted,
    OrderFailed,
    OrderFilled,
    OrderPlaced,
    RiskBreached,
)
from openticker.ports.errors import BrokerError
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Exchange,
    InstrumentType,
    Interval,
    Product,
    Side,
)
from openticker.storage.calendar_file import load_calendar
from openticker.use_cases.connect_broker import connect_broker as connect_broker_use_case
from openticker.use_cases.evaluate_risk import evaluate_risk as evaluate_risk_use_case
from openticker.use_cases.get_audit_log import get_audit_log as get_audit_log_use_case
from openticker.use_cases.get_funds import get_funds as get_funds_use_case
from openticker.use_cases.get_historical_bars import (
    get_historical_bars as get_historical_bars_use_case,
)
from openticker.use_cases.get_market_status import (
    get_market_status as get_market_status_use_case,
)
from openticker.use_cases.get_option_chain import NoOptionsError
from openticker.use_cases.get_option_chain import get_option_chain as get_option_chain_use_case
from openticker.use_cases.get_orderbook import get_orderbook as get_orderbook_use_case
from openticker.use_cases.get_positions import get_positions as get_positions_use_case
from openticker.use_cases.get_quote import get_quote as get_quote_use_case
from openticker.use_cases.place_order import place_order as place_order_use_case
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument
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
4. get_option_chain on an index (NIFTY 50, NIFTY BANK, SENSEX, ...) or a stock for
   strikes, prices, IV and Greeks around at-the-money.
5. Trading is paper trading only (a local sandbox with virtual capital): place_order
   never sends anything to the broker, and fills only while the exchange is open
   (get_market_status). evaluate_risk checks stop/target settings first;
   get_positions, get_funds and get_orderbook show the result.

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
DEFAULT_AUDIT_LIMIT = 20
DEFAULT_STRIKE_COUNT = 10
DEFAULT_ORDERBOOK_LIMIT = 20
EVENT_TYPE_NAMES = [
    event.__name__
    for event in (
        OrderPlaced,
        OrderFilled,
        OrderFailed,
        RiskBreached,
        InstrumentSyncCompleted,
        BrokerSessionExpired,
    )
]

# The tools' clock; tests replace it to run at a fixed market time.
clock: Callable[[], datetime] = lambda: datetime.now(UTC)

_event_bus: EventBus | None = None
_event_bus_lock = threading.Lock()


def event_bus() -> EventBus:
    """Built on first use (or by `main`), after the environment is loaded.
    Tools run on worker threads, so two first calls can race; the lock keeps
    it to one bus."""
    global _event_bus
    with _event_bus_lock:
        if _event_bus is None:
            _event_bus = build_event_bus(os.environ)
        return _event_bus


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
    UnsupportedUnderlyingError,
    NoOptionsError,
    SandboxConfigError,
    CalendarError,
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
        count = sync_instruments_use_case(broker, get_adapter(broker), event_bus())
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
    include_expired: Annotated[bool, Field(description="Include contracts past expiry.")] = False,
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
    return SearchResult.of(found, limit)


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
    return BarsResult.of(symbol, exchange, interval, bars, max_bars)


@mcp.tool(
    title="Get option chain",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def get_option_chain(
    broker: Broker,
    underlying: Annotated[
        str,
        Field(
            description="The underlying's own symbol, not an option's: NIFTY 50, NIFTY BANK, "
            "NIFTY FIN SERVICE, NIFTY MID SELECT, NIFTY NEXT 50, SENSEX, BANKEX, or a stock "
            "such as RELIANCE."
        ),
    ],
    exchange: Annotated[
        Exchange, Field(description="The underlying's exchange: NSE, or BSE for SENSEX/BANKEX.")
    ],
    expiry: Annotated[
        date | None,
        Field(description="Expiry date. Omit for the nearest; the result lists all of them."),
    ] = None,
    strike_count: Annotated[
        int, Field(ge=1, le=50, description="Strikes to show either side of at-the-money.")
    ] = DEFAULT_STRIKE_COUNT,
    interest_rate: Annotated[
        float,
        Field(ge=0, le=20, description="Annualized risk-free rate in percent, for the Greeks."),
    ] = 0.0,
) -> OptionChainResult:
    """Calls and puts for one expiry around at-the-money: live price, open
    interest, implied volatility and Greeks (Black-76 on the forward implied by
    the ATM pair). Needs sync_instruments to have run today."""
    now = datetime.now(UTC)
    with _agent_facing_errors():
        chain, expiries = get_option_chain_use_case(
            get_adapter(broker),
            underlying,
            exchange.value,
            expiry,
            strike_count,
            interest_rate / 100,
            now,
        )
    return OptionChainResult.of(chain, expiries, now)


Quantity = Annotated[
    int, Field(ge=1, description="Units, not lots: a multiple of the lot size for F&O.")
]
SideParam = Annotated[Side, Field(description="BUY or SELL.")]
Price = Annotated[float | None, Field(gt=0)]


@mcp.tool(
    title="Place sandbox order",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
def place_order(
    broker: Broker,
    symbol: Symbol,
    exchange: ExchangeParam,
    side: SideParam,
    quantity: Quantity,
    product: Annotated[
        Product,
        Field(
            description="MIS: intraday (equity or F&O). NRML: F&O carried overnight. "
            "CNC: equity delivery (can't be sold short)."
        ),
    ],
    order_type: Annotated[
        OrderType, Field(description="Only MARKET is supported for now.")
    ] = OrderType.MARKET,
    price: Annotated[Price, Field(description="Limit price; leave unset for MARKET.")] = None,
) -> PlaceOrderResult:
    """Paper trade: fill a MARKET order in the local sandbox at the broker's
    live price. Nothing is sent to the broker. Checks the order shape, the
    capital cap and virtual funds first; a rejection says why."""
    with _agent_facing_errors():
        request = OrderRequest(
            instrument=resolve_instrument(symbol, exchange.value),
            side=side,
            quantity=quantity,
            product=product,
            order_type=order_type,
            price=price,
            triggered_by="mcp",
        )
        result = place_order_use_case(
            request,
            order_broker(broker, os.environ),
            event_bus(),
            capital_cap(os.environ),
            load_calendar(),
            clock(),
        )
    return PlaceOrderResult.of(
        request,
        result,
        "get_positions shows the position and its P&L."
        if result.status is OrderStatus.FILLED
        else "Fix what the reason says and place the order again.",
    )


@mcp.tool(
    title="Get market status",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_market_status(
    exchange: Annotated[Exchange | None, Field(description="Omit for every exchange.")] = None,
) -> MarketStatusesResult:
    """Whether each exchange is open now, and its current or next session's
    hours. Knows weekends, exchange holidays and special sessions."""
    exchanges = [exchange] if exchange is not None else list(Exchange)
    with _agent_facing_errors():
        statuses = get_market_status_use_case(exchanges, clock())
    return MarketStatusesResult(exchanges=[MarketStatusResult.of(status) for status in statuses])


@mcp.tool(
    title="Get sandbox positions",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def get_positions(
    broker: Broker,
    include_closed: Annotated[
        bool, Field(description="Also list positions closed earlier, with their realized P&L.")
    ] = False,
) -> PositionsResult:
    """Sandbox net positions valued at the broker's live prices."""
    with _agent_facing_errors():
        positions = get_positions_use_case(order_broker(broker, os.environ))
    return PositionsResult.of(positions, include_closed)


@mcp.tool(
    title="Get sandbox funds",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_funds(broker: Broker) -> FundsResult:
    """Virtual capital, margin in use and realized P&L in the sandbox."""
    with _agent_facing_errors():
        funds = get_funds_use_case(order_broker(broker, os.environ))
    return FundsResult.of(funds)


@mcp.tool(
    title="Get sandbox order book",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_orderbook(
    broker: Broker,
    limit: Annotated[int, Field(ge=1, le=200, description="Most orders to return.")] = (
        DEFAULT_ORDERBOOK_LIMIT
    ),
) -> OrderbookResult:
    """Sandbox orders, filled and rejected, most recent first."""
    with _agent_facing_errors():
        orders = get_orderbook_use_case(order_broker(broker, os.environ), limit)
    return OrderbookResult.of(orders)


@mcp.tool(
    title="Evaluate position risk",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def evaluate_risk(
    broker: Broker,
    symbol: Symbol,
    exchange: ExchangeParam,
    side: Annotated[Side, Field(description="BUY for a long position, SELL for a short.")],
    quantity: Quantity,
    entry_price: Annotated[
        Price, Field(description="Omit to evaluate entering now, at the live price.")
    ] = None,
    stop_loss: Annotated[Price, Field(description="Exit price if the trade goes wrong.")] = None,
    target: Annotated[Price, Field(description="Exit price if the trade goes right.")] = None,
    capital_cap: Annotated[
        Price, Field(description="Most the position may be worth, in rupees.")
    ] = None,
) -> RiskCheckResult:
    """Would these stop loss, target and capital cap settings exit right now,
    and are any of them on the wrong side of the market? Places nothing."""
    with _agent_facing_errors():
        check = evaluate_risk_use_case(
            get_adapter(broker),
            symbol,
            exchange.value,
            side,
            quantity,
            entry_price,
            stop_loss,
            target,
            capital_cap,
        )
    return RiskCheckResult.of(check)


@mcp.tool(
    title="Get audit log",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def get_audit_log(
    event_type: Annotated[
        str | None,
        Field(description=f"Only this event type: {', '.join(EVENT_TYPE_NAMES)}."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Most entries to return.")] = (
        DEFAULT_AUDIT_LIMIT
    ),
) -> AuditLogResult:
    """What OpenTicker has done, most recent first: every order, risk breach
    and instrument sync, with who triggered it. Local data only."""
    return AuditLogResult.of(get_audit_log_use_case(limit, event_type))


def main() -> None:
    load_dotenv()  # process entry point only — importing this module must stay side-effect-free
    atexit.register(event_bus().close)  # built now so bad notification settings fail at startup
    mcp.run()


if __name__ == "__main__":
    main()
