"""Tool result shapes. Each becomes the tool's `outputSchema`, so every field
carries a description the agent reads. Times are exchange-local (IST offset
included), matching the trading dates the tools take as input. The REST API
returns the same shapes (ADR 8 and ADR 17 in docs/adr)."""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, WithJsonSchema

from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobStatus,
    Verdict,
    verdict_of,
)
from openticker.core.agents.reviews import MAX_AFTER_RUNS, ReviewSchedule, every_text
from openticker.core.calendar.models import MarketStatus
from openticker.core.options.models import GreeksModel, OptionChain, OptionQuote
from openticker.core.orders.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Trade,
)
from openticker.core.orders.sandbox import PaperMargin
from openticker.core.pnl import DayPnl, Source, source_of
from openticker.core.risk.models import (
    BreachReason,
    LockMode,
    ProfitLock,
    StrategyLimits,
    StrategyStopReason,
)
from openticker.core.scripts.models import (
    InvalidScriptError,
    ScriptCommand,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptLimits,
    ScriptRun,
    ScriptRunStatus,
    ScriptSchedule,
    ScriptStopReason,
)
from openticker.core.strategies.ledger import LedgerFill, LedgerRun, LedgerTotals
from openticker.core.strategies.models import (
    MAX_LEGS,
    MAX_LOTS,
    MAX_STRIKE_OFFSET,
    Direction,
    Horizon,
    InvalidStrategyError,
    LegSpec,
    OptionsStrategySpec,
    RelativeExpiry,
    RiskValue,
    Schedule,
    SignalLeg,
    SignalStrategySpec,
    StrikeSelector,
)
from openticker.core.strategies.runs import (
    Command,
    CommandKind,
    CommandStatus,
    LegStatus,
    Run,
    RunLeg,
    RunStatus,
)
from openticker.core.strategies.signals import SignalAction
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Bar,
    DepthLevel,
    Exchange,
    Funds,
    Instrument,
    InstrumentType,
    Interval,
    MarginRequirement,
    MarketDepth,
    Position,
    Product,
    Quote,
    Side,
)
from openticker.storage.sqlite.audit_repo import AuditEntry
from openticker.storage.sqlite.scripts_repo import StoredScript
from openticker.storage.sqlite.signals_repo import StoredWebhook
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.storage.sqlite.watchlists_repo import Watchlist
from openticker.use_cases.agents.manage import AgentJobLog
from openticker.use_cases.check_charge_rates import ChargeRateCheck, SampleCheck
from openticker.use_cases.evaluate_risk import RiskCheck
from openticker.use_cases.get_quotes import QuotesLookup
from openticker.use_cases.place_basket import BasketOrder, BasketPlacement
from openticker.use_cases.pnl_history import ChargeTotals, PnlHistory
from openticker.use_cases.position_holders import Holder, Holding, PositionKey, key_of
from openticker.use_cases.preview_charges import ChargePreview
from openticker.use_cases.preview_payoff import PayoffLegRequest, PayoffPreview
from openticker.use_cases.scripts.manage import ScriptDetail, ScriptLog, ScriptSummary
from openticker.use_cases.strategies.board import BoardRow, Segment, StrategyState
from openticker.use_cases.strategies.control import RunDetail, SignalsDetail
from openticker.use_cases.strategies.define import StrategyPreview
from openticker.use_cases.strategies.ledger import StrategyLedger

# Exchange-local wall-clock time, "09:20" or "09:20:00". JSON Schema's "time"
# format (RFC 3339) requires a UTC offset, so clients that check formats,
# MCP Inspector among them, would refuse the plain times these fields take.
ExchangeTime = Annotated[
    time,
    WithJsonSchema({"type": "string", "pattern": r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"}),
]


class LoginUrlResult(BaseModel):
    broker: str
    login_url: str = Field(description="Open in a browser and log in on the broker's own page.")
    next_step: str


class ConnectResult(BaseModel):
    broker: str
    connected: bool
    next_step: str


class SyncResult(BaseModel):
    broker: str
    instrument_count: int = Field(description="Instruments written to the local master.")


class InstrumentResult(BaseModel):
    symbol: str = Field(description="Standardized symbol — pass this to other tools.")
    exchange: Exchange
    instrument_type: InstrumentType
    expiry: date | None
    strike: float | None
    lot_size: int = Field(description="Order quantity must be a multiple of this.")
    tick_size: float

    @classmethod
    def of(cls, instrument: Instrument) -> "InstrumentResult":
        return cls(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            instrument_type=instrument.instrument_type,
            expiry=instrument.expiry,
            strike=instrument.strike,
            lot_size=instrument.lot_size,
            tick_size=instrument.tick_size,
        )


class SearchResult(BaseModel):
    instruments: list[InstrumentResult]
    truncated: bool = Field(description="More matches exist; narrow the query or filters.")

    @classmethod
    def of(cls, found: Sequence[Instrument], limit: int) -> "SearchResult":
        """`found` holds up to `limit + 1` matches; the extra one means more exist."""
        return cls(
            instruments=[InstrumentResult.of(instrument) for instrument in found[:limit]],
            truncated=len(found) > limit,
        )


class QuoteResult(BaseModel):
    symbol: str
    exchange: Exchange
    last_price: float
    as_of: datetime = Field(description="Time of the last trade, exchange-local.")
    bid: float | None = Field(description="Best price a buyer is waiting at; None if none.")
    ask: float | None = Field(description="Best price a seller is waiting at; None if none.")
    bid_quantity: int | None = Field(description="Units waiting at the best bid.")
    ask_quantity: int | None = Field(description="Units waiting at the best ask.")
    open: float | None = Field(description="Today's open; None before the first trade.")
    high: float | None = Field(description="Today's high.")
    low: float | None = Field(description="Today's low.")
    prev_close: float | None = Field(description="The previous session's close.")
    volume: int | None = Field(description="Units traded today.")
    open_interest: int | None = Field(description="Futures and options only.")

    @classmethod
    def of(cls, quote: Quote) -> "QuoteResult":
        return cls(
            symbol=quote.instrument.symbol,
            exchange=quote.instrument.exchange,
            last_price=quote.last_price,
            as_of=quote.as_of.astimezone(EXCHANGE_TIMEZONE),
            bid=quote.bid,
            ask=quote.ask,
            bid_quantity=quote.bid_quantity,
            ask_quantity=quote.ask_quantity,
            open=quote.open,
            high=quote.day_high,
            low=quote.day_low,
            prev_close=quote.close,
            volume=quote.volume,
            open_interest=quote.open_interest,
        )


class DepthLevelResult(BaseModel):
    price: float
    quantity: int = Field(description="Units waiting at this price.")
    orders: int = Field(description="Orders making up that quantity.")

    @classmethod
    def of(cls, level: DepthLevel) -> "DepthLevelResult":
        return cls(price=level.price, quantity=level.quantity, orders=level.orders)


class MarketDepthResult(BaseModel):
    symbol: str
    exchange: Exchange
    as_of: datetime = Field(description="Time of the last trade, exchange-local.")
    last_price: float
    last_quantity: int | None = Field(description="Units in the last trade.")
    bids: list[DepthLevelResult] = Field(
        description="Buyers waiting, best (highest) first; up to 5, empty levels left out."
    )
    asks: list[DepthLevelResult] = Field(
        description="Sellers waiting, best (lowest) first; up to 5, empty levels left out."
    )
    total_buy_quantity: int = Field(description="Units buyers are waiting for, whole book.")
    total_sell_quantity: int = Field(description="Units sellers are offering, whole book.")
    open: float | None = Field(description="Today's open; None before the first trade.")
    high: float | None = Field(description="Today's high.")
    low: float | None = Field(description="Today's low.")
    prev_close: float | None = Field(description="The previous session's close.")
    volume: int | None = Field(description="Units traded today.")
    open_interest: int | None = Field(description="Futures and options only.")

    @classmethod
    def of(cls, depth: MarketDepth) -> "MarketDepthResult":
        return cls(
            symbol=depth.instrument.symbol,
            exchange=depth.instrument.exchange,
            as_of=depth.as_of.astimezone(EXCHANGE_TIMEZONE),
            last_price=depth.last_price,
            last_quantity=depth.last_quantity,
            bids=[DepthLevelResult.of(level) for level in depth.bids],
            asks=[DepthLevelResult.of(level) for level in depth.asks],
            total_buy_quantity=depth.total_buy_quantity,
            total_sell_quantity=depth.total_sell_quantity,
            open=depth.open,
            high=depth.high,
            low=depth.low,
            prev_close=depth.close,
            volume=depth.volume,
            open_interest=depth.open_interest,
        )


class InstrumentRef(BaseModel):
    symbol: str = Field(description="OpenTicker's symbol, e.g. SBIN, NIFTY29SEP26FUT.")
    exchange: Exchange


class MissingQuoteResult(BaseModel):
    symbol: str
    exchange: str
    reason: str


class QuotesResult(BaseModel):
    quotes: list[QuoteResult] = Field(description="In the order asked, repeats once.")
    missing: list[MissingQuoteResult] = Field(
        description="Instruments not quoted, each with why: not in the instrument master "
        "(check with search_instruments, or run sync_instruments), or no quote from the broker."
    )

    @classmethod
    def of(cls, lookup: QuotesLookup) -> "QuotesResult":
        return cls(
            quotes=[QuoteResult.of(quote) for quote in lookup.quotes],
            missing=[
                MissingQuoteResult(symbol=m.symbol, exchange=m.exchange, reason=m.reason)
                for m in lookup.missing
            ],
        )


class BarResult(BaseModel):
    timestamp: datetime = Field(description="Candle open time, exchange-local.")
    open: float
    high: float
    low: float
    close: float
    volume: int

    @classmethod
    def of(cls, bar: Bar) -> "BarResult":
        return cls(
            timestamp=bar.timestamp.astimezone(EXCHANGE_TIMEZONE),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )


class BarsResult(BaseModel):
    symbol: str
    exchange: Exchange
    interval: Interval
    total_bars: int = Field(description="Bars in the requested range, all stored locally.")
    bars: list[BarResult] = Field(description="Oldest first; the most recent `max_bars` only.")
    note: str | None = Field(description="Set when `bars` was cut short, with what to do.")

    @classmethod
    def of(
        cls, symbol: str, exchange: Exchange, interval: Interval, bars: Sequence[Bar], max_bars: int
    ) -> "BarsResult":
        returned = bars[-max_bars:]
        return cls(
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


TRIGGERED_BY_DESCRIPTION = (
    "Who caused it, as recorded: ui (the web app), mcp:<client> (an MCP client by name; "
    "plain mcp before clients were named), rest:<key name>, strategy:<id>, webhook, "
    "script:<id>, schedule, or the server itself (square-off, expiry-settlement)."
)
SOURCE_DESCRIPTION = "triggered_by read as who did it, as the web app labels it."


class AuditEntryResult(BaseModel):
    id: int
    occurred_at: datetime = Field(description="Exchange-local.")
    event_type: str
    triggered_by: str | None = Field(description=TRIGGERED_BY_DESCRIPTION)
    source: Source = Field(description=SOURCE_DESCRIPTION)
    details: dict[str, Any] = Field(description="The event's own fields.")

    @classmethod
    def of(cls, entry: AuditEntry) -> "AuditEntryResult":
        return cls(
            id=entry.id,
            occurred_at=entry.occurred_at.astimezone(EXCHANGE_TIMEZONE),
            event_type=entry.event_type,
            triggered_by=entry.triggered_by,
            source=source_of(entry.triggered_by),
            details=json.loads(entry.payload),
        )


class AuditLogResult(BaseModel):
    entries: list[AuditEntryResult] = Field(description="Most recent first.")

    @classmethod
    def of(cls, entries: Sequence[AuditEntry]) -> "AuditLogResult":
        return cls(entries=[AuditEntryResult.of(entry) for entry in entries])


class OptionQuoteResult(BaseModel):
    symbol: str
    label: str = Field(description="ATM, or ITM<n>/OTM<n>: listed strikes from at-the-money.")
    last_price: float | None = Field(description="None when the contract has no usable price.")
    open_interest: int | None
    greeks_model: GreeksModel | None = Field(
        description="implied: from the implied volatility. intrinsic: no time value left to "
        "solve from, so delta is 1/-1 in the money and 0 out of it, the rest 0. None: unpriced."
    )
    implied_volatility: float | None = Field(description="Annualized, in percent.")
    delta: float | None
    gamma: float | None
    theta: float | None = Field(description="Price change per calendar day.")
    vega: float | None = Field(description="Price change per 1 point of volatility.")
    rho: float | None = Field(description="Price change per 1 point of interest rate.")
    bid: float | None = Field(description="Best bid; None when nobody is bidding.")
    ask: float | None = Field(description="Best offer; None when nobody is offering.")

    @classmethod
    def of(cls, option: OptionQuote) -> "OptionQuoteResult":
        greeks = option.greeks
        return cls(
            symbol=option.instrument.symbol,
            label=option.label,
            last_price=option.last_price,
            open_interest=option.open_interest,
            greeks_model=greeks.model if greeks else None,
            implied_volatility=(
                round(greeks.implied_volatility * 100, 2)
                if greeks and greeks.implied_volatility is not None
                else None
            ),
            delta=round(greeks.delta, 4) if greeks else None,
            gamma=round(greeks.gamma, 6) if greeks else None,
            theta=round(greeks.theta, 4) if greeks else None,
            vega=round(greeks.vega, 4) if greeks else None,
            rho=round(greeks.rho, 4) if greeks else None,
            bid=option.bid,
            ask=option.ask,
        )


class ChainRowResult(BaseModel):
    strike: float
    call: OptionQuoteResult | None
    put: OptionQuoteResult | None


class OptionChainResult(BaseModel):
    underlying: str
    exchange: Exchange
    underlying_price: float
    forward_price: float = Field(
        description="Implied by put-call parity at the ATM strike; the underlying price when "
        "either ATM leg is unpriced. Greeks are priced off this (Black-76)."
    )
    expiry: date
    expires_at: datetime = Field(description="15:30 on expiry day, exchange-local.")
    days_to_expiry: float
    atm_strike: float
    interest_rate: float = Field(description="Annualized, in percent, used for the Greeks.")
    rows: list[ChainRowResult] = Field(description="Ascending strike.")
    available_expiries: list[date] = Field(description="Unexpired expiries, earliest first.")
    lot_size: int | None = Field(description="Units in one lot of these options.")
    futures: list["ChainFutureResult"] = Field(
        description="The nearest two futures on the same underlying, earliest first."
    )

    @classmethod
    def of(cls, chain: OptionChain, expiries: list[date], now: datetime) -> "OptionChainResult":
        contracts = [
            option.instrument for row in chain.rows for option in (row.call, row.put) if option
        ]
        return cls(
            underlying=chain.underlying.symbol,
            exchange=chain.underlying.exchange,
            underlying_price=chain.underlying_price,
            forward_price=round(chain.forward_price, 2),
            expiry=chain.expiry,
            expires_at=chain.expires_at.astimezone(EXCHANGE_TIMEZONE),
            days_to_expiry=round((chain.expires_at - now).total_seconds() / 86400, 3),
            atm_strike=chain.atm_strike,
            interest_rate=round(chain.interest_rate * 100, 4),
            rows=[
                ChainRowResult(
                    strike=row.strike,
                    call=OptionQuoteResult.of(row.call) if row.call else None,
                    put=OptionQuoteResult.of(row.put) if row.put else None,
                )
                for row in chain.rows
            ],
            available_expiries=expiries,
            lot_size=contracts[0].lot_size if contracts else None,
            futures=[ChainFutureResult.of(quote) for quote in chain.futures],
        )


class ChainFutureResult(BaseModel):
    symbol: str
    expiry: date
    last_price: float
    bid: float | None
    ask: float | None
    lot_size: int

    @classmethod
    def of(cls, quote: Quote) -> "ChainFutureResult":
        assert quote.instrument.expiry is not None
        return cls(
            symbol=quote.instrument.symbol,
            expiry=quote.instrument.expiry,
            last_price=quote.last_price,
            bid=quote.bid or None,
            ask=quote.ask or None,
            lot_size=quote.instrument.lot_size,
        )


class MarketStatusResult(BaseModel):
    exchange: Exchange
    is_open: bool
    closed_reason: str | None = Field(
        description="Why it is closed now: weekend, a holiday's name, before or after the session."
    )
    session_opens_at: datetime = Field(
        description="The session in progress, else the next one. Exchange-local."
    )
    session_closes_at: datetime
    session_name: str | None = Field(description="Set for a special session, e.g. Muhurat.")
    holidays_known: bool = Field(
        description="False when the holiday list doesn't cover this year: weekdays are then "
        "assumed open, and a holiday would go unnoticed."
    )

    @classmethod
    def of(cls, status: MarketStatus) -> "MarketStatusResult":
        return cls(
            exchange=status.exchange,
            is_open=status.is_open,
            closed_reason=status.closed_reason,
            session_opens_at=status.session.opens_at,
            session_closes_at=status.session.closes_at,
            session_name=status.session.name,
            holidays_known=status.holidays_known,
        )


class MarketStatusesResult(BaseModel):
    exchanges: list[MarketStatusResult]


class PlaceOrderResult(BaseModel):
    order_id: str | None = Field(description="Sandbox order id; None when rejected before it.")
    status: OrderStatus = Field(
        description="FILLED; PENDING for a LIMIT/SL/SL-M order resting in the sandbox; "
        "or REJECTED/FAILED with a reason."
    )
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    product: Product
    fill_price: float | None
    reason: str | None = Field(description="Why it was not filled.")
    next_step: str

    @classmethod
    def of(cls, request: OrderRequest, result: OrderResult, next_step: str) -> "PlaceOrderResult":
        return cls(
            order_id=result.broker_order_id,
            status=result.status,
            symbol=request.instrument.symbol,
            exchange=request.instrument.exchange,
            side=request.side,
            quantity=request.quantity,
            product=request.product,
            fill_price=result.fill_price,
            reason=result.reason,
            next_step=next_step,
        )


class OrderInput(BaseModel):
    """One order of a basket: place_order's fields."""

    symbol: str = Field(description="OpenTicker's symbol, e.g. SBIN, NIFTY29SEP26FUT.")
    exchange: Exchange
    side: Side = Field(description="BUY or SELL.")
    quantity: int = Field(ge=1, description="Units, not lots: a multiple of the lot size for F&O.")
    product: Product = Field(
        description="MIS: intraday. NRML: F&O carried overnight. CNC: equity delivery."
    )
    order_type: OrderType = Field(
        default=OrderType.MARKET, description="MARKET, LIMIT, SL or SL-M, as in place_order."
    )
    price: float | None = Field(default=None, gt=0, description="Limit price: LIMIT and SL only.")
    trigger_price: float | None = Field(default=None, gt=0, description="SL and SL-M only.")

    def to_order(self) -> BasketOrder:
        return BasketOrder(
            symbol=self.symbol,
            exchange=self.exchange,
            side=self.side,
            quantity=self.quantity,
            product=self.product,
            order_type=self.order_type,
            price=self.price,
            trigger_price=self.trigger_price,
        )


class BasketResult(BaseModel):
    orders: list[PlaceOrderResult] = Field(
        description="In placing order: every BUY, then every SELL. One refused doesn't "
        "stop the rest; each says its own status and reason."
    )

    @classmethod
    def of(
        cls, placements: Sequence[BasketPlacement], next_step: Callable[[OrderStatus], str]
    ) -> "BasketResult":
        return cls(
            orders=[
                PlaceOrderResult(
                    order_id=placed.result.broker_order_id,
                    status=placed.result.status,
                    symbol=placed.order.symbol,
                    exchange=placed.order.exchange,
                    side=placed.order.side,
                    quantity=placed.order.quantity,
                    product=placed.order.product,
                    fill_price=placed.result.fill_price,
                    reason=placed.result.reason,
                    next_step=next_step(placed.result.status),
                )
                for placed in placements
            ]
        )


class MarginResult(BaseModel):
    total: float = Field(description="What the broker would block, hedge benefit included.")
    span: float
    exposure: float
    option_premium: float = Field(description="Premium paid for option buys.")
    benefit: float = Field(
        description="The broker's hedge benefit for the set (its initial margin less its "
        "final one). Placing the orders one at a time would need more still. 0 for one order."
    )
    note: str = Field(
        default="The broker's margin, for the real account (its open positions count). The "
        "sandbox blocks by its own rule; get_funds shows what it holds."
    )

    @classmethod
    def of(cls, margin: MarginRequirement) -> "MarginResult":
        return cls(
            total=margin.total,
            span=margin.span,
            exposure=margin.exposure,
            option_premium=margin.option_premium,
            benefit=margin.benefit,
        )


class PaperMarginResult(BaseModel):
    required: float = Field(
        description="What the paper account would block for the part of the order that opens "
        "or adds to a position. 0 when it only closes."
    )
    released: float = Field(description="What the part that closes a position would free.")
    available: float = Field(description="Cash free in the paper account now.")
    fits: bool = Field(
        description="The funds cover it; a fill at this price wouldn't be refused for margin."
    )

    @classmethod
    def of(cls, margin: PaperMargin) -> "PaperMarginResult":
        return cls(
            required=margin.required,
            released=margin.released,
            available=margin.available,
            fits=margin.fits,
        )


class PayoffLegInput(BaseModel):
    """One leg of a position to preview: an option or a future."""

    symbol: str = Field(description="OpenTicker's symbol, e.g. NIFTY29SEP2624800CE.")
    exchange: Exchange = Field(description="NFO or BFO.")
    side: Side = Field(description="BUY or SELL.")
    quantity: int = Field(ge=1, description="Units, not lots.")
    price: float | None = Field(
        default=None, ge=0, description="The price to assume; omit for the last price."
    )

    def to_request(self) -> PayoffLegRequest:
        return PayoffLegRequest(self.symbol, self.exchange, self.side, self.quantity, self.price)


class PayoffLegResult(BaseModel):
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float = Field(description="The price the payoff assumes.")
    implied_volatility: float | None = Field(
        description="Percent, from the last price; None for a future or an unpriced option."
    )


class PayoffPointResult(BaseModel):
    underlying: float
    at_expiry: float
    today: float | None


class PayoffResult(BaseModel):
    underlying: str
    exchange: Exchange
    underlying_price: float
    legs: list[PayoffLegResult]
    net_premium: float = Field(description="Rupees; positive is a credit.")
    max_profit: float | None = Field(description="Rupees at expiry; None: unbounded.")
    max_loss: float | None = Field(
        description="The lowest P&L at expiry, rupees, negative for a loss; None: unbounded."
    )
    breakevens: list[float] = Field(description="Underlying prices at expiry, ascending.")
    net_delta: float | None = Field(
        description="Rupees per point of the underlying, today; None when an option is unpriced."
    )
    points: list[PayoffPointResult] = Field(
        description="P&L at expiry and today (Black-76 at each leg's IV) across the underlying, "
        "161 points, ±8% of it or wider to take in every strike."
    )

    @classmethod
    def of(cls, preview: PayoffPreview) -> "PayoffResult":
        result = preview.payoff
        return cls(
            underlying=preview.underlying.symbol,
            exchange=preview.underlying.exchange,
            underlying_price=preview.spot,
            legs=[
                PayoffLegResult(
                    symbol=leg.instrument.symbol,
                    exchange=leg.instrument.exchange,
                    side=leg.side,
                    quantity=leg.quantity,
                    price=leg.price,
                    implied_volatility=(
                        round(leg.implied_volatility * 100, 2)
                        if leg.implied_volatility is not None
                        else None
                    ),
                )
                for leg in preview.legs
            ],
            net_premium=result.net_premium,
            max_profit=result.max_profit,
            max_loss=result.max_loss,
            breakevens=list(result.breakevens),
            net_delta=result.net_delta,
            points=[
                PayoffPointResult(underlying=p.underlying, at_expiry=p.at_expiry, today=p.today)
                for p in result.points
            ],
        )


class ChargesResult(BaseModel):
    segment: str = Field(description="equity_delivery, equity_intraday, futures or options.")
    exchange: Exchange
    items: dict[str, float] = Field(
        description="brokerage, transaction_tax (STT), exchange_txn, sebi, stamp_duty and gst, "
        "in rupees."
    )
    total: float
    rates_source: str = Field(description="Where the rates come from.")
    rates_as_of: date = Field(description="When they were last confirmed.")

    @classmethod
    def of(cls, preview: ChargePreview) -> "ChargesResult":
        schedule = preview.schedule
        return cls(
            segment=schedule.segment.value,
            exchange=schedule.exchange,
            items=dict(preview.charges.items),
            total=preview.charges.total,
            rates_source=schedule.source,
            rates_as_of=schedule.as_of,
        )


class ChargeDifferenceResult(BaseModel):
    item: str = Field(description="A charge (brokerage, transaction_tax, ...), gst or total.")
    ours: float
    broker: float


class ChargeSampleResult(BaseModel):
    segment: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float
    ours: float = Field(description="Total at the rates the sandbox charges.")
    broker: float = Field(description="Total on the broker's contract note.")
    differences: list[ChargeDifferenceResult] = Field(
        description="Figures more than a paisa apart; empty when they agree."
    )

    @classmethod
    def of(cls, check: SampleCheck) -> "ChargeSampleResult":
        sample = check.sample
        return cls(
            segment=sample.segment.value,
            symbol=sample.instrument.symbol,
            exchange=sample.instrument.exchange,
            side=sample.side,
            quantity=sample.quantity,
            price=sample.price,
            ours=check.ours.total,
            broker=check.broker.total,
            differences=[
                ChargeDifferenceResult(item=d.key, ours=d.ours, broker=d.broker)
                for d in check.differences
            ],
        )


class ChargeCheckResult(BaseModel):
    broker: str
    checked_at: datetime
    matches: bool = Field(description="Every sample priced the same by both, to the paisa.")
    rates_source: str
    rates_as_of: date
    samples: list[ChargeSampleResult]
    skipped: list[str] = Field(description="Segments with no sample, and why.")
    next_step: str

    @classmethod
    def of(cls, check: ChargeRateCheck) -> "ChargeCheckResult":
        matches = not check.differing
        return cls(
            broker=check.broker,
            checked_at=check.checked_at.astimezone(EXCHANGE_TIMEZONE),
            matches=matches,
            rates_source=check.rates_source,
            rates_as_of=check.rates_as_of,
            samples=[ChargeSampleResult.of(sample) for sample in check.samples],
            skipped=list(check.skipped),
            next_step="Nothing to do: paper fills pay what the broker would charge."
            if matches
            else "Tell the user: the charges file needs the broker's figures. They can put "
            "corrected rates in $OPENTICKER_HOME/charges.json, which replaces the shipped file.",
        )


class CancelOrderResult(BaseModel):
    order_id: str
    status: OrderStatus = Field(description="CANCELLED, or the status that kept it from being.")
    reason: str | None

    @classmethod
    def of(cls, order_id: str, result: OrderResult) -> "CancelOrderResult":
        return cls(order_id=order_id, status=result.status, reason=result.reason)


class CancelAllResult(BaseModel):
    cancelled: list[str] = Field(description="Ids of the orders withdrawn.")
    failed: list[CancelOrderResult] = Field(
        description="Orders that were pending but filled or went before they could be withdrawn."
    )

    @classmethod
    def of(cls, outcomes: Sequence[tuple[Order, OrderResult]]) -> "CancelAllResult":
        return cls(
            cancelled=[o.order_id for o, r in outcomes if r.status is OrderStatus.CANCELLED],
            failed=[
                CancelOrderResult.of(o.order_id, r)
                for o, r in outcomes
                if r.status is not OrderStatus.CANCELLED
            ],
        )


def closing_result(
    position: Position, result: OrderResult, next_step: Callable[[OrderStatus], str]
) -> PlaceOrderResult:
    """The order that closes `position`: the other side, for what was held."""
    return PlaceOrderResult(
        order_id=result.broker_order_id,
        status=result.status,
        symbol=position.instrument.symbol,
        exchange=position.instrument.exchange,
        side=Side.SELL if position.quantity > 0 else Side.BUY,
        quantity=abs(position.quantity),
        product=position.product,
        fill_price=result.fill_price,
        reason=result.reason,
        next_step=next_step(result.status),
    )


class CloseAllResult(BaseModel):
    orders: list[PlaceOrderResult] = Field(
        description="One per open position. One that couldn't close (exchange closed, no "
        "fresh price, expired) says why; the rest still closed."
    )

    @classmethod
    def of(
        cls,
        closed: Sequence[tuple[Position, OrderResult]],
        next_step: Callable[[OrderStatus], str],
    ) -> "CloseAllResult":
        return cls(orders=[closing_result(p, r, next_step) for p, r in closed])


class HolderResult(BaseModel):
    strategy_id: str | None = Field(description="None: the part no running strategy holds.")
    name: str | None = Field(description="The strategy's name; None for the rest.")
    source: Source = Field(
        description="strategy, or for the rest who last added to it (you, claude-code, ...)."
    )
    quantity: int = Field(description="Net and signed, as the position's.")
    leg_ids: list[str] = Field(
        description="The strategy's open legs on this contract: close_strategy_leg takes one."
    )

    @classmethod
    def of(cls, holder: Holder) -> "HolderResult":
        return cls(
            strategy_id=holder.strategy_id,
            name=holder.name,
            source=holder.source,
            quantity=holder.quantity,
            leg_ids=list(holder.leg_ids),
        )


class PositionResult(BaseModel):
    symbol: str
    exchange: Exchange
    instrument_type: InstrumentType
    expiry: date | None
    strike: float | None
    lot_size: int
    product: Product
    quantity: int = Field(description="Net and signed: negative is short, 0 is closed.")
    average_price: float
    last_price: float | None = Field(description="None when no fresh price was available.")
    unrealized_pnl: float | None
    realized_pnl: float
    held_by: list[HolderResult] = Field(
        description="Running strategies holding part of it, then the rest; empty when closed."
    )
    shared: bool = Field(
        description="True when the strategies' legs don't fit inside the position (opposite "
        "sides, or more than it holds): closing it closes what they think they hold."
    )

    @classmethod
    def of(cls, position: Position, holding: Holding | None = None) -> "PositionResult":
        instrument = position.instrument
        return cls(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            instrument_type=instrument.instrument_type,
            expiry=instrument.expiry,
            strike=instrument.strike,
            lot_size=instrument.lot_size,
            product=position.product,
            quantity=position.quantity,
            average_price=round(position.average_price, 4),
            last_price=position.last_price,
            unrealized_pnl=(
                round(position.unrealized_pnl, 2) if position.unrealized_pnl is not None else None
            ),
            realized_pnl=round(position.realized_pnl, 2),
            held_by=[HolderResult.of(h) for h in holding.holders] if holding else [],
            shared=holding.shared if holding else False,
        )


class PositionsResult(BaseModel):
    positions: list[PositionResult]
    total_unrealized_pnl: float | None = Field(
        description="None when any open position has no current price."
    )
    total_realized_pnl: float

    @classmethod
    def of(
        cls,
        positions: Sequence[Position],
        include_closed: bool,
        holdings: Mapping[PositionKey, Holding] | None = None,
    ) -> "PositionsResult":
        shown = [position for position in positions if include_closed or position.quantity]
        unrealized = [position.unrealized_pnl for position in shown]
        held = holdings or {}
        return cls(
            positions=[PositionResult.of(p, held.get(key_of(p))) for p in shown],
            total_unrealized_pnl=(
                None
                if any(value is None for value in unrealized)
                else round(sum(value or 0.0 for value in unrealized), 2)
            ),
            total_realized_pnl=round(sum(position.realized_pnl for position in positions), 2),
        )


class FundsResult(BaseModel):
    total_capital: float = Field(description="Virtual starting capital.")
    available_cash: float = Field(
        description="Capital - used margin + realized P&L - charges paid."
    )
    used_margin: float
    realized_pnl: float = Field(description="What closed trades made or lost, before charges.")
    charges: float = Field(
        description="Brokerage, taxes and exchange fees paid on every paper fill."
    )

    @classmethod
    def of(cls, funds: Funds) -> "FundsResult":
        return cls(
            total_capital=funds.total_capital,
            available_cash=round(funds.available_cash, 2),
            used_margin=round(funds.used_margin, 2),
            realized_pnl=round(funds.realized_pnl, 2),
            charges=round(funds.charges, 2),
        )


class OrderbookEntryResult(BaseModel):
    order_id: str
    placed_at: datetime = Field(description="Exchange-local.")
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    product: Product
    order_type: OrderType
    price: float | None = Field(description="Limit price: LIMIT and SL orders.")
    trigger_price: float | None = Field(description="SL and SL-M orders.")
    status: OrderStatus = Field(
        description="PENDING rests until a live price crosses it; CANCELLED includes orders "
        "that expired at the session's end."
    )
    fill_price: float | None
    reason: str | None
    triggered: bool = Field(
        description="An SL order whose trigger has been crossed: it now rests as a limit order."
    )
    triggered_by: str = Field(description=TRIGGERED_BY_DESCRIPTION)
    source: Source = Field(description=SOURCE_DESCRIPTION)
    placed_by: str | None = Field(
        default=None,
        description="The name of the strategy or hosted script that placed it; None for "
        "anyone else, or when it has since been deleted.",
    )
    strategy_id: str | None
    instrument_type: InstrumentType
    expiry: date | None
    strike: float | None
    lot_size: int

    @classmethod
    def of(cls, order: Order, names: Mapping[str, str] | None = None) -> "OrderbookEntryResult":
        """`names`: placer_names for the strategies and scripts among the orders."""
        instrument = order.instrument
        return cls(
            order_id=order.order_id,
            placed_at=order.placed_at.astimezone(EXCHANGE_TIMEZONE),
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            side=order.side,
            quantity=order.quantity,
            product=order.product,
            order_type=order.order_type,
            price=order.price,
            trigger_price=order.trigger_price,
            status=order.status,
            fill_price=order.fill_price,
            reason=order.reason,
            triggered=order.triggered,
            triggered_by=order.triggered_by,
            source=source_of(order.triggered_by),
            placed_by=(names or {}).get(order.triggered_by),
            strategy_id=order.strategy_id,
            instrument_type=instrument.instrument_type,
            expiry=instrument.expiry,
            strike=instrument.strike,
            lot_size=instrument.lot_size,
        )


class ModifyOrderResult(BaseModel):
    order_id: str
    status: OrderStatus = Field(
        description="PENDING: the change is made. REJECTED/FAILED: the order is unchanged, "
        "for the reason given. FILLED/CANCELLED: it had already left the book."
    )
    reason: str | None
    order: OrderbookEntryResult | None = Field(description="The order as it is now.")
    next_step: str

    @classmethod
    def of(cls, order_id: str, result: OrderResult, order: Order | None) -> "ModifyOrderResult":
        return cls(
            order_id=order_id,
            status=result.status,
            reason=result.reason,
            order=OrderbookEntryResult.of(order) if order is not None else None,
            next_step=(
                "Rests at its new terms until a live price crosses it; openticker-serve fills "
                "it. get_order_status shows it."
                if result.status is OrderStatus.PENDING
                else "Nothing changed. Fix what the reason says, or cancel_order and place "
                "a new one to change anything else."
            ),
        )


class OrderbookResult(BaseModel):
    orders: list[OrderbookEntryResult] = Field(description="Most recent first.")

    @classmethod
    def of(
        cls, orders: Sequence[Order], names: Mapping[str, str] | None = None
    ) -> "OrderbookResult":
        return cls(orders=[OrderbookEntryResult.of(order, names) for order in orders])


class TradeResult(BaseModel):
    order_id: str
    filled_at: datetime = Field(description="Exchange-local.")
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float = Field(description="Fill price: a market order pays the ask or gets the bid.")
    expected_price: float | None = Field(
        description="What the order was placed against: the last price for a market order, "
        "the limit or trigger for a resting one. None for trades before costs were modelled."
    )
    value: float = Field(description="price x quantity.")
    charges: float | None = Field(
        description="Brokerage, taxes and exchange fees on this fill. None: not modelled for "
        "this instrument (MCX), or a trade from before charges were."
    )
    product: Product
    charges_detail: dict[str, float] | None = Field(
        description="The charges itemised: brokerage, transaction_tax (STT), exchange_txn, "
        "sebi, stamp_duty and gst; they sum to charges. None: not modelled, or a trade from "
        "before they were recorded."
    )
    realized_pnl: float | None = Field(
        description="What this fill closed made or lost, before charges; 0 for one that only "
        "opened. None: a trade from before it was recorded."
    )
    triggered_by: str = Field(description=TRIGGERED_BY_DESCRIPTION)
    source: Source = Field(description=SOURCE_DESCRIPTION)
    placed_by: str | None = Field(
        default=None,
        description="The name of the strategy or hosted script that placed it; None for "
        "anyone else, or when it has since been deleted.",
    )
    strategy_id: str | None
    run_id: str | None
    instrument_type: InstrumentType
    expiry: date | None
    strike: float | None
    lot_size: int

    @classmethod
    def of(cls, trade: Trade, names: Mapping[str, str] | None = None) -> "TradeResult":
        return cls(
            order_id=trade.order_id,
            filled_at=trade.filled_at.astimezone(EXCHANGE_TIMEZONE),
            symbol=trade.instrument.symbol,
            exchange=trade.instrument.exchange,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            expected_price=trade.expected_price,
            value=round(trade.price * trade.quantity, 2),
            charges=trade.charges,
            charges_detail=dict(trade.charges_detail) if trade.charges_detail else None,
            realized_pnl=trade.realized_pnl,
            product=trade.product,
            triggered_by=trade.triggered_by,
            source=source_of(trade.triggered_by),
            placed_by=(names or {}).get(trade.triggered_by),
            strategy_id=trade.strategy_id,
            run_id=trade.run_id,
            instrument_type=trade.instrument.instrument_type,
            expiry=trade.instrument.expiry,
            strike=trade.instrument.strike,
            lot_size=trade.instrument.lot_size,
        )


class TradebookResult(BaseModel):
    trades: list[TradeResult] = Field(description="Newest first.")
    since: datetime = Field(
        description="Start of the period (today, this week or this month), exchange-local."
    )

    @classmethod
    def of(
        cls, trades: Sequence[Trade], since: datetime, names: Mapping[str, str] | None = None
    ) -> "TradebookResult":
        return cls(
            trades=[TradeResult.of(trade, names) for trade in trades],
            since=since.astimezone(EXCHANGE_TIMEZONE),
        )


class RiskCheckResult(BaseModel):
    last_price: float
    breached: bool = Field(description="True when the settings would exit at this price now.")
    reason: BreachReason | None
    detail: str | None
    stop_loss: float | None
    unrealized_pnl: float = Field(description="At the last price, from the entry price.")
    exit_side: Side | None = Field(description="The order side that would close the position.")
    warnings: list[str] = Field(description="Settings that would exit at once or trail badly.")

    @classmethod
    def of(cls, check: RiskCheck) -> "RiskCheckResult":
        decision = check.decision
        return cls(
            last_price=check.last_price,
            breached=decision.breached,
            reason=decision.reason,
            detail=decision.detail,
            stop_loss=decision.stop_loss,
            unrealized_pnl=round(decision.unrealized_pnl, 2),
            exit_side=decision.exit_side,
            warnings=check.warnings,
        )


class RiskValueInput(BaseModel):
    value: float = Field(gt=0, description="Distance from the leg's entry price.")
    percent: bool = Field(
        default=False, description="True: percent of the entry price. False: price points."
    )

    def to_core(self) -> RiskValue:
        return RiskValue(value=self.value, percent=self.percent)

    @classmethod
    def of(cls, value: RiskValue | None) -> "RiskValueInput | None":
        return None if value is None else cls(value=value.value, percent=value.percent)


class LegDefinition(BaseModel):
    side: Side = Field(description="BUY or SELL.")
    lots: int = Field(ge=1, le=MAX_LOTS, description="Lots; units are this times the lot size.")
    option_type: Literal["CE", "PE", "FUT"] = Field(description="Call, put or future.")
    expiry: RelativeExpiry = Field(
        description="weekly: nearest expiry (needs weekly contracts, e.g. NIFTY, SENSEX). "
        "next_week: the one after. monthly: last expiry of the nearest month. next_month: "
        "last expiry of the month after. Futures take monthly or next_month."
    )
    strike_offset: int = Field(
        default=0,
        ge=-MAX_STRIKE_OFFSET,
        le=MAX_STRIKE_OFFSET,
        description="Listed strikes from at the money (ATM is the strike nearest the "
        "underlying's price): 0 ATM, +2 two strikes out of the money, -1 one strike in the "
        "money, for this leg's option type. Options only.",
    )
    fixed_strike: float | None = Field(
        default=None, gt=0, description="A specific strike instead of an offset. Options only."
    )
    stop_loss: RiskValueInput | None = Field(default=None, description="This leg's own stop.")
    target: RiskValueInput | None = Field(default=None, description="This leg's own target.")
    trailing: RiskValueInput | None = Field(
        default=None, description="Trailing stop distance; trails from the entry price."
    )

    def to_core(self) -> LegSpec:
        option_type = InstrumentType(self.option_type)
        options = option_type is not InstrumentType.FUT
        strike = (
            StrikeSelector(offset=self.strike_offset, fixed_strike=self.fixed_strike)
            if options
            else None
        )
        if not options and (self.strike_offset or self.fixed_strike is not None):
            raise InvalidStrategyError("a futures leg has no strike")
        return LegSpec(
            side=self.side,
            lots=self.lots,
            option_type=option_type,
            expiry=self.expiry,
            strike=strike,
            stop_loss=self.stop_loss.to_core() if self.stop_loss else None,
            target=self.target.to_core() if self.target else None,
            trailing=self.trailing.to_core() if self.trailing else None,
        )

    @classmethod
    def of(cls, leg: LegSpec) -> "LegDefinition":
        return cls(
            side=leg.side,
            lots=leg.lots,
            option_type=leg.option_type.value,  # type: ignore[arg-type]
            expiry=leg.expiry,
            strike_offset=leg.strike.offset if leg.strike else 0,
            fixed_strike=leg.strike.fixed_strike if leg.strike else None,
            stop_loss=RiskValueInput.of(leg.stop_loss),
            target=RiskValueInput.of(leg.target),
            trailing=RiskValueInput.of(leg.trailing),
        )


class ProfitLockDefinition(BaseModel):
    arm_at: float = Field(gt=0, description="Strategy P&L, in rupees, that arms the lock.")
    lock: float = Field(
        ge=0,
        description="Once armed, exit everything if P&L falls back to this. Below arm_at; "
        "0 locks breakeven.",
    )
    mode: LockMode = Field(
        default=LockMode.LOCK,
        description="lock: the floor stays at `lock`. lock_and_trail: the floor rises by "
        "trail_step for every trail_step the peak P&L climbs beyond arm_at.",
    )
    trail_step: float | None = Field(default=None, gt=0, description="lock_and_trail only.")


class _LimitFields(BaseModel):
    """Strategy-wide limits, the same for both kinds of strategy."""

    combined_stop_loss: float | None = Field(
        default=None, gt=0, description="Exit everything at this total loss, in rupees."
    )
    combined_target: float | None = Field(
        default=None, gt=0, description="Exit everything at this total profit, in rupees."
    )
    lock_profit: ProfitLockDefinition | None = Field(
        default=None, description="Lock in profit once the strategy is up enough."
    )
    stops_to_entry_on_leg_stop: bool = Field(
        default=False,
        description="When one leg's stop loss fires, move every other open leg's stop to its "
        "entry (where that tightens it) and stop applying combined_stop_loss.",
    )
    daily_loss_limit: float | None = Field(
        default=None,
        gt=0,
        description="Stop for the day once today's runs have lost this much, in rupees.",
    )

    def _limits(self) -> StrategyLimits:
        lock = self.lock_profit
        return StrategyLimits(
            combined_stop_loss=self.combined_stop_loss,
            combined_target=self.combined_target,
            lock_profit=None
            if lock is None
            else ProfitLock(
                arm_at=lock.arm_at, lock=lock.lock, mode=lock.mode, trail_step=lock.trail_step
            ),
            stops_to_entry_on_leg_stop=self.stops_to_entry_on_leg_stop,
            daily_loss_limit=self.daily_loss_limit,
        )

    @staticmethod
    def _limit_values(limits: StrategyLimits) -> dict[str, Any]:
        lock = limits.lock_profit
        return {
            "combined_stop_loss": limits.combined_stop_loss,
            "combined_target": limits.combined_target,
            "lock_profit": None
            if lock is None
            else ProfitLockDefinition(
                arm_at=lock.arm_at, lock=lock.lock, mode=lock.mode, trail_step=lock.trail_step
            ),
            "stops_to_entry_on_leg_stop": limits.stops_to_entry_on_leg_stop,
            "daily_loss_limit": limits.daily_loss_limit,
        }


class StrategyDefinition(_LimitFields):
    """An options strategy whose legs are chosen relative to the market, so the
    same definition trades the right contracts on any day."""

    underlying: str = Field(description="Index or stock, e.g. NIFTY 50, NIFTY BANK, SENSEX.")
    exchange: Literal["NSE", "BSE"] = Field(description="The underlying's exchange.")
    horizon: Horizon = Field(
        description="intraday: MIS, closed by exit_time or the 15:15 square-off. "
        "positional: NRML, carried overnight."
    )
    legs: list[LegDefinition] = Field(
        min_length=1,
        max_length=MAX_LEGS,
        description=f"1 to {MAX_LEGS} legs, named leg1, leg2, ... in this order.",
    )
    entry_time: ExchangeTime | None = Field(
        default=None,
        description="HH:MM exchange time to enter on scheduled days, once schedule_strategy "
        "arms it; omit to enter only on start_strategy.",
    )
    exit_time: ExchangeTime | None = Field(
        default=None,
        description="HH:MM exchange time to close every run, each trading day, scheduled or "
        "not. Omit to hold a positional strategy across days.",
    )
    weekdays: list[int] = Field(
        default=[0, 1, 2, 3, 4],
        description="Days scheduled entries run, 0 Monday to 4 Friday. Market holidays are "
        "always skipped.",
    )
    exit_on_expiry: bool = Field(
        default=True,
        description="On the expiry day of any contract held, close at exit_time (or the 15:15 "
        "square-off) instead of being settled at expiry.",
    )

    def to_spec(self) -> OptionsStrategySpec:
        try:
            return OptionsStrategySpec(
                underlying=self.underlying,
                exchange=Exchange(self.exchange),
                legs=tuple(leg.to_core() for leg in self.legs),
                horizon=self.horizon,
                schedule=Schedule(
                    entry_time=self.entry_time,
                    exit_time=self.exit_time,
                    weekdays=frozenset(self.weekdays),
                    exit_on_expiry=self.exit_on_expiry,
                ),
                limits=self._limits(),
            )
        except InvalidStrategyError:
            raise
        except ValueError as exc:
            raise InvalidStrategyError(str(exc)) from exc

    @classmethod
    def of(cls, spec: OptionsStrategySpec) -> "StrategyDefinition":
        schedule = spec.schedule
        return cls(
            underlying=spec.underlying,
            exchange=spec.exchange.value,  # type: ignore[arg-type]
            horizon=spec.horizon,
            legs=[LegDefinition.of(leg) for leg in spec.legs],
            entry_time=schedule.entry_time,
            exit_time=schedule.exit_time,
            weekdays=sorted(schedule.weekdays),
            exit_on_expiry=schedule.exit_on_expiry,
            **cls._limit_values(spec.limits),
        )


class SignalLegDefinition(BaseModel):
    symbol: str = Field(
        min_length=1,
        description="The exact contract, as search_instruments shows it: a stock (RELIANCE), "
        "a future or an option.",
    )
    exchange: Exchange = Field(description="The contract's exchange: NSE, BSE, NFO, BFO, MCX.")
    quantity: int = Field(
        ge=1, description="Units; for a derivative, a whole number of lots times the lot size."
    )
    accepts: Direction = Field(
        default=Direction.BOTH,
        description="Which alerts this leg takes: both, long_only (long_entry, long_exit) or "
        "short_only (short_entry, short_exit).",
    )
    stop_loss: RiskValueInput | None = Field(default=None, description="Each position's stop.")
    target: RiskValueInput | None = Field(default=None, description="Each position's target.")
    trailing: RiskValueInput | None = Field(
        default=None, description="Trailing stop distance; trails from the entry price."
    )

    def to_core(self) -> SignalLeg:
        return SignalLeg(
            symbol=self.symbol.strip().upper(),
            exchange=self.exchange,
            quantity=self.quantity,
            accepts=self.accepts,
            stop_loss=self.stop_loss.to_core() if self.stop_loss else None,
            target=self.target.to_core() if self.target else None,
            trailing=self.trailing.to_core() if self.trailing else None,
        )

    @classmethod
    def of(cls, leg: SignalLeg) -> "SignalLegDefinition":
        return cls(
            symbol=leg.symbol,
            exchange=leg.exchange,
            quantity=leg.quantity,
            accepts=leg.accepts,
            stop_loss=RiskValueInput.of(leg.stop_loss),
            target=RiskValueInput.of(leg.target),
            trailing=RiskValueInput.of(leg.trailing),
        )


class SignalStrategyDefinition(_LimitFields):
    """A strategy alerts drive: each alert enters or exits one of its legs,
    which name their contracts outright."""

    horizon: Horizon = Field(
        description="intraday: MIS, closed by exit_time or the 15:15 square-off. "
        "positional: NRML, carried overnight."
    )
    direction: Direction = Field(
        default=Direction.BOTH,
        description="Which positions alerts may open: both, long_only or short_only. An alert "
        "for the other side is refused.",
    )
    legs: list[SignalLegDefinition] = Field(
        min_length=1,
        max_length=MAX_LEGS,
        description=f"1 to {MAX_LEGS} contracts, named leg1, leg2, ... in this order; each "
        "trades a different contract.",
    )
    entry_time: ExchangeTime | None = Field(
        default=None, description="HH:MM exchange time entry alerts are taken from each day."
    )
    exit_time: ExchangeTime | None = Field(
        default=None,
        description="HH:MM exchange time that closes whatever is held each trading day; no "
        "alert is taken after it.",
    )
    weekdays: list[int] = Field(
        default=[0, 1, 2, 3, 4],
        description="Days entry alerts are taken, 0 Monday to 4 Friday.",
    )
    exit_on_expiry: bool = Field(
        default=True,
        description="On the expiry day of a derivative held, close it at exit_time (or the "
        "15:15 square-off) instead of being settled at expiry.",
    )

    def to_spec(self) -> SignalStrategySpec:
        try:
            return SignalStrategySpec(
                legs=tuple(leg.to_core() for leg in self.legs),
                horizon=self.horizon,
                direction=self.direction,
                schedule=Schedule(
                    entry_time=self.entry_time,
                    exit_time=self.exit_time,
                    weekdays=frozenset(self.weekdays),
                    exit_on_expiry=self.exit_on_expiry,
                ),
                limits=self._limits(),
            )
        except InvalidStrategyError:
            raise
        except ValueError as exc:
            raise InvalidStrategyError(str(exc)) from exc

    @classmethod
    def of(cls, spec: SignalStrategySpec) -> "SignalStrategyDefinition":
        schedule = spec.schedule
        return cls(
            horizon=spec.horizon,
            direction=spec.direction,
            legs=[SignalLegDefinition.of(leg) for leg in spec.legs],
            entry_time=schedule.entry_time,
            exit_time=schedule.exit_time,
            weekdays=sorted(schedule.weekdays),
            exit_on_expiry=schedule.exit_on_expiry,
            **cls._limit_values(spec.limits),
        )


class ReviewScheduleDefinition(BaseModel):
    """When openticker-serve reviews a strategy without being asked. Any
    trigger met is enough; each counts from the last review, or from when
    the schedule was set. A review is due only once a run has ended since
    the last one."""

    every: str | None = Field(
        default=None,
        description="A review at most this often, like 30m, 4h or 1d (5 minutes to 90 days).",
    )
    after_runs: int | None = Field(
        default=None,
        ge=1,
        le=MAX_AFTER_RUNS,
        description="A review once this many runs have ended after costs since the last one.",
    )
    drawdown: float | None = Field(
        default=None,
        gt=0,
        description="A review when net P&L after charges falls this many rupees below its high.",
    )


class ReviewScheduleResult(BaseModel):
    every: str | None
    after_runs: int | None
    drawdown: float | None
    set_at: datetime

    @classmethod
    def of(cls, schedule: ReviewSchedule) -> "ReviewScheduleResult":
        return cls(
            every=every_text(schedule.every) if schedule.every is not None else None,
            after_runs=schedule.after_runs,
            drawdown=schedule.drawdown,
            set_at=schedule.set_at.astimezone(EXCHANGE_TIMEZONE),
        )


class StrategyResult(BaseModel):
    strategy_id: str = Field(description="Pass this to the other strategy tools.")
    name: str
    kind: Literal["options", "signal"] = Field(
        description="options: legs chosen relative to the market, entered on start_strategy "
        "or a schedule. signal: legs entered and exited by alerts."
    )
    mode: str = Field(description="sandbox: every order is paper traded.")
    locked: bool = Field(description="True while the kill switch is on.")
    scheduled_broker: str | None = Field(
        description="The broker its scheduled entries go through; null when it enters only "
        "on start_strategy."
    )
    review_schedule: ReviewScheduleResult | None = Field(
        description="When openticker-serve reviews it without being asked; null when only "
        "start_review does."
    )
    definition: StrategyDefinition | SignalStrategyDefinition
    created_at: datetime
    updated_at: datetime
    next_step: str | None = None

    @classmethod
    def of(cls, stored: StoredStrategy, next_step: str | None = None) -> "StrategyResult":
        return cls(
            strategy_id=stored.id,
            name=stored.name,
            kind="signal" if isinstance(stored.spec, SignalStrategySpec) else "options",
            mode=stored.mode,
            locked=stored.locked,
            scheduled_broker=stored.scheduled_broker,
            review_schedule=ReviewScheduleResult.of(stored.review_schedule)
            if stored.review_schedule is not None
            else None,
            definition=SignalStrategyDefinition.of(stored.spec)
            if isinstance(stored.spec, SignalStrategySpec)
            else StrategyDefinition.of(stored.spec),
            created_at=stored.created_at.astimezone(EXCHANGE_TIMEZONE),
            updated_at=stored.updated_at.astimezone(EXCHANGE_TIMEZONE),
            next_step=next_step,
        )


class StrategySummary(BaseModel):
    strategy_id: str
    name: str
    kind: Literal["options", "signal"]
    underlying: str = Field(
        description="An options strategy's underlying; a signal strategy's contracts."
    )
    legs: int
    horizon: Horizon
    locked: bool
    scheduled: bool = Field(description="True when it enters on its schedule.")
    review_scheduled: bool = Field(description="True when it is reviewed on a schedule.")
    updated_at: datetime
    state: StrategyState = Field(
        description="killed: its kill switch is on. running: a run is open, or a start is "
        "waiting for openticker-serve. listening: a signal strategy with an alert URL and "
        "nothing open. scheduled: enters on its schedule. stopped."
    )
    segments: list[Segment] = Field(description="What it trades: EQ, FUT, OPT.")
    next_entry: datetime | None = Field(description="When a scheduled strategy enters next.")
    exit_time: ExchangeTime | None = Field(description="Its daily square-off, exchange-local.")
    active_run: "ActiveRunResult | None" = Field(description="The open run, with its legs.")
    pending: CommandKind | None = Field(
        description="A start, stop, kill or close_leg openticker-serve hasn't carried out yet."
    )
    today_pnl: float = Field(
        description="Runs started today and the open run: realized P&L less charges, rupees. "
        "Open legs' unrealized P&L is not in it."
    )
    net_pnl: float = Field(description="Every run after costs, less charges (as the ledger).")
    runs: int = Field(description="Every run it has had.")
    judged_runs: int = Field(description="Runs after costs: the ones net_pnl and wins count.")
    wins: int
    max_drawdown: float = Field(description="Deepest fall of net P&L from its high, run by run.")
    last_run_at: datetime | None = Field(description="When the newest run started.")
    has_alert_url: bool = Field(description="A signal strategy with an alert URL.")
    last_review: "ReviewBriefResult | None" = Field(description="The newest review that answered.")

    @classmethod
    def of(cls, row: BoardRow) -> "StrategySummary":
        stored = row.strategy
        signal = isinstance(stored.spec, SignalStrategySpec)
        return cls(
            strategy_id=stored.id,
            name=stored.name,
            kind="signal" if signal else "options",
            underlying=", ".join(leg.symbol for leg in stored.spec.legs)
            if isinstance(stored.spec, SignalStrategySpec)
            else stored.spec.underlying,
            legs=len(stored.spec.legs),
            horizon=stored.spec.horizon,
            locked=stored.locked,
            scheduled=stored.scheduled_broker is not None,
            review_scheduled=stored.review_schedule is not None,
            updated_at=stored.updated_at.astimezone(EXCHANGE_TIMEZONE),
            state=row.state,
            segments=list(row.segments),
            next_entry=_local(row.next_entry),
            exit_time=stored.spec.schedule.exit_time,
            active_run=ActiveRunResult.of(row.active_run) if row.active_run else None,
            pending=row.pending,
            today_pnl=row.today_net,
            net_pnl=row.net_pnl,
            runs=row.runs,
            judged_runs=row.judged,
            wins=row.wins,
            max_drawdown=row.max_drawdown,
            last_run_at=_local(row.last_run_at),
            has_alert_url=row.has_alert_url,
            last_review=ReviewBriefResult.of(row.review) if row.review else None,
        )


class StrategiesResult(BaseModel):
    strategies: list[StrategySummary] = Field(description="By name.")


class DeleteStrategyResult(BaseModel):
    strategy_id: str
    deleted: bool


class PreviewLegResult(BaseModel):
    leg_id: str
    side: Side
    lots: int
    quantity: int = Field(description="Units: lots times the lot size.")
    symbol: str
    exchange: Exchange
    expiry: date | None
    strike: float | None
    label: str = Field(description="ATM, ITM<n> or OTM<n> in listed strikes, or FUT.")
    last_price: float | None


class StrategyPreviewResult(BaseModel):
    strategy_id: str
    name: str
    underlying: str
    underlying_price: float = Field(description="ATM is the listed strike nearest this.")
    legs: list[PreviewLegResult]
    net_premium: float | None = Field(
        description="Rupees received minus paid at last prices: positive is a credit. None "
        "when a leg has no price."
    )
    next_step: str

    @classmethod
    def of(cls, preview: StrategyPreview, next_step: str) -> "StrategyPreviewResult":
        return cls(
            strategy_id=preview.strategy.id,
            name=preview.strategy.name,
            underlying=preview.underlying.symbol,
            underlying_price=preview.underlying_price,
            legs=[
                PreviewLegResult(
                    leg_id=leg.leg_id,
                    side=leg.spec.side,
                    lots=leg.spec.lots,
                    quantity=leg.quantity,
                    symbol=leg.instrument.symbol,
                    exchange=leg.instrument.exchange,
                    expiry=leg.instrument.expiry,
                    strike=leg.instrument.strike,
                    label=leg.label,
                    last_price=leg.last_price,
                )
                for leg in preview.legs
            ],
            net_premium=preview.net_premium,
            next_step=next_step,
        )


def _local(moment: datetime | None) -> datetime | None:
    return moment.astimezone(EXCHANGE_TIMEZONE) if moment is not None else None


class StrategyCommandResult(BaseModel):
    strategy_id: str
    command_id: int
    command: CommandKind
    status: CommandStatus = Field(
        description="pending: openticker-serve carries it out within about a second."
    )
    locked: bool = Field(description="True while the kill switch is on.")
    next_step: str

    @classmethod
    def of(cls, command: Command, locked: bool, next_step: str) -> "StrategyCommandResult":
        return cls(
            strategy_id=command.strategy_id,
            command_id=command.id,
            command=command.kind,
            status=command.status,
            locked=locked,
            next_step=next_step,
        )


class CommandResult(BaseModel):
    command_id: int
    command: CommandKind
    leg_id: str | None
    action: SignalAction | None = Field(default=None, description="An alert's, for a signal.")
    status: CommandStatus
    outcome: str | None = Field(description="What happened, or why it was refused.")
    triggered_by: str
    created_at: datetime
    processed_at: datetime | None

    @classmethod
    def of(cls, command: Command) -> "CommandResult":
        return cls(
            command_id=command.id,
            command=command.kind,
            leg_id=command.leg_id,
            action=command.action,
            status=command.status,
            outcome=command.outcome,
            triggered_by=command.triggered_by,
            created_at=command.created_at.astimezone(EXCHANGE_TIMEZONE),
            processed_at=_local(command.processed_at),
        )


class RunSummary(BaseModel):
    run_id: str = Field(description="Pass to get_strategy_run for legs, orders and timeline.")
    status: RunStatus = Field(
        description="open: holding legs under watch. stopping: closing them. ended."
    )
    trigger: str = Field(description="Who started it.")
    started_at: datetime
    ended_at: datetime | None
    stop_reason: StrategyStopReason | None
    stop_detail: str | None
    realized_pnl: float = Field(description="Rupees from legs closed so far.")

    @classmethod
    def of(cls, run: Run) -> "RunSummary":
        return cls(
            run_id=run.id,
            status=run.status,
            trigger=run.trigger,
            started_at=run.started_at.astimezone(EXCHANGE_TIMEZONE),
            ended_at=_local(run.ended_at),
            stop_reason=run.stop_reason,
            stop_detail=run.stop_detail,
            realized_pnl=run.realized_pnl,
        )


class LedgerFillResult(BaseModel):
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float
    filled_at: datetime
    expected_price: float | None = Field(
        description="What the order was placed against; null: filled before costs were modelled."
    )
    slippage: float | None = Field(
        description="Rupees paid beyond the expected price (negative: a better fill)."
    )
    charges: float | None = Field(description="null: filled before costs were modelled.")

    @classmethod
    def of(cls, fill: LedgerFill) -> "LedgerFillResult":
        return cls(
            symbol=fill.symbol,
            exchange=Exchange(fill.exchange),
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            filled_at=fill.filled_at.astimezone(EXCHANGE_TIMEZONE),
            expected_price=fill.expected_price,
            slippage=fill.slippage,
            charges=fill.charges,
        )


class LedgerRunResult(BaseModel):
    run_id: str
    status: RunStatus
    trigger: str = Field(description="Who started it.")
    started_at: datetime
    ended_at: datetime | None
    stop_reason: StrategyStopReason | None
    stop_detail: str | None
    gross_pnl: float = Field(description="Realized P&L of its legs, before charges.")
    charges: float
    net_pnl: float = Field(description="gross_pnl less charges.")
    slippage: float = Field(description="Already inside gross_pnl; shown to tell fills from rules.")
    peak_mtm: float = Field(description="Its best mark-to-market while open.")
    trough_mtm: float = Field(description="Its worst mark-to-market while open.")
    after_costs: bool = Field(description="Ended, every fill paid charges: counted in totals.")
    fills: list[LedgerFillResult] = Field(description="Oldest first.")

    @classmethod
    def of(cls, entry: LedgerRun) -> "LedgerRunResult":
        run = entry.run
        return cls(
            run_id=run.id,
            status=run.status,
            trigger=run.trigger,
            started_at=run.started_at.astimezone(EXCHANGE_TIMEZONE),
            ended_at=_local(run.ended_at),
            stop_reason=run.stop_reason,
            stop_detail=run.stop_detail,
            gross_pnl=entry.gross_pnl,
            charges=entry.charges,
            net_pnl=entry.net_pnl,
            slippage=entry.slippage,
            peak_mtm=run.peak_mtm,
            trough_mtm=run.trough_mtm,
            after_costs=entry.after_costs,
            fills=[LedgerFillResult.of(fill) for fill in entry.fills],
        )


class EquityPointResult(BaseModel):
    day: date = Field(description="Exchange-local trading date.")
    net_pnl: float = Field(description="Cumulative, after costs, rupees.")


class LedgerTotalsResult(BaseModel):
    runs: int = Field(description="Runs after costs: the ones these totals judge.")
    wins: int = Field(description="Runs with net P&L above zero.")
    losses: int
    gross_pnl: float
    charges: float
    net_pnl: float
    slippage: float
    average_win: float | None
    average_loss: float | None
    best_run: float | None
    worst_run: float | None
    max_drawdown: float = Field(
        description="Deepest fall of cumulative net P&L from its high, run by run."
    )
    stop_reasons: dict[str, int] = Field(description="How the runs ended, most common first.")

    @classmethod
    def of(cls, totals: LedgerTotals) -> "LedgerTotalsResult":
        return cls(**{field: getattr(totals, field) for field in cls.model_fields})


class StrategyLedgerResult(BaseModel):
    strategy_id: str
    name: str
    kind: str
    total_runs: int = Field(description="Every run it has had.")
    uncharged: int = Field(
        description="Ended runs with a fill that recorded no charges (filled before costs were "
        "modelled, or on MCX, whose charges aren't yet); left out of totals."
    )
    open_runs: int = Field(description="Not ended; left out of totals.")
    totals: LedgerTotalsResult = Field(description="Over the runs after costs, all of them.")
    runs: list[LedgerRunResult] = Field(description="The newest runs, newest first.")
    equity: list[EquityPointResult] = Field(
        description="Cumulative net P&L after costs at the end of each day it ran, oldest "
        "first; the latest 750 days."
    )

    @classmethod
    def of(cls, ledger: StrategyLedger) -> "StrategyLedgerResult":
        return cls(
            strategy_id=ledger.strategy.id,
            name=ledger.strategy.name,
            kind=ledger.strategy.kind,
            total_runs=ledger.total_runs,
            uncharged=ledger.uncharged,
            open_runs=ledger.open_runs,
            totals=LedgerTotalsResult.of(ledger.totals),
            runs=[LedgerRunResult.of(run) for run in ledger.runs],
            equity=[EquityPointResult(day=p.day, net_pnl=p.net_pnl) for p in ledger.equity],
        )


class AgentJobResult(BaseModel):
    job_id: str
    kind: str = Field(description="review: reads one strategy and writes its verdict in the note.")
    strategy_id: str
    harness: str = Field(description="The coding agent that runs it: claude or codex.")
    status: AgentJobStatus = Field(
        description="pending: waiting for openticker-serve, which runs one job at a time. "
        "running, stopping, or ended."
    )
    trigger: str = Field(description="Who asked for it.")
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: AgentJobEndReason | None
    end_detail: str | None
    summary: str | None = Field(
        description="The agent's final answer; a review's starts with its verdict."
    )
    verdict: Verdict | None = Field(
        default=None, description="The verdict the summary leads with, when it leads with one."
    )
    cost_usd: float | None = Field(description="What the run cost, when the harness reports it.")

    @classmethod
    def of(cls, job: AgentJob) -> "AgentJobResult":
        return cls(
            job_id=job.id,
            kind=job.kind,
            strategy_id=job.strategy_id,
            harness=job.harness,
            status=job.status,
            trigger=job.trigger,
            created_at=job.created_at.astimezone(EXCHANGE_TIMEZONE),
            started_at=_local(job.started_at),
            ended_at=_local(job.ended_at),
            end_reason=job.end_reason,
            end_detail=job.end_detail,
            summary=job.summary,
            verdict=verdict_of(job.summary),
            cost_usd=job.cost_usd,
        )


class StartReviewResult(BaseModel):
    job: AgentJobResult
    next_step: str = Field(
        default="openticker-serve starts it within a few seconds if no other job is running; "
        "it writes its verdict into the strategy's note in labs/notes/. get_agent_jobs shows "
        "when it ends, get_agent_job_log what it printed."
    )


class AgentJobsResult(BaseModel):
    jobs: list[AgentJobResult] = Field(description="Newest first.")


class AgentJobLogResult(BaseModel):
    job_id: str
    status: AgentJobStatus
    log: str = Field(description="The end of what the agent printed while it worked.")
    truncated: bool = Field(description="True when older output was left out.")

    @classmethod
    def of(cls, job_log: AgentJobLog) -> "AgentJobLogResult":
        return cls(
            job_id=job_log.job.id,
            status=job_log.job.status,
            log=job_log.text,
            truncated=job_log.truncated,
        )


class StrategyRunsResult(BaseModel):
    strategy_id: str
    name: str
    locked: bool = Field(description="True while the kill switch is on.")
    runs: list[RunSummary] = Field(description="Newest first.")
    commands: list[CommandResult] = Field(description="Latest requests, newest first.")

    @classmethod
    def of(
        cls, stored: StoredStrategy, runs: Sequence[Run], commands: Sequence[Command]
    ) -> "StrategyRunsResult":
        return cls(
            strategy_id=stored.id,
            name=stored.name,
            locked=stored.locked,
            runs=[RunSummary.of(run) for run in runs],
            commands=[CommandResult.of(command) for command in commands],
        )


class RunLegResult(BaseModel):
    leg_id: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int = Field(description="Units.")
    status: LegStatus = Field(
        description="pending, open, closing (exit sent or being retried), closed, or failed "
        "(never entered)."
    )
    entry_price: float | None
    exit_price: float | None
    exit_reason: str | None = Field(
        description="stop_loss, target, manual, or the run's stop reason."
    )
    stop_loss: float | None = Field(description="Where the stop is now, after any trailing.")
    target: float | None
    realized_pnl: float

    @classmethod
    def of(cls, leg: RunLeg) -> "RunLegResult":
        risk = leg.risk
        return cls(
            leg_id=leg.leg_id,
            symbol=leg.symbol,
            exchange=leg.exchange,
            side=leg.side,
            quantity=leg.quantity,
            status=leg.status,
            entry_price=leg.entry_price,
            exit_price=leg.exit_price,
            exit_reason=leg.exit_reason,
            stop_loss=(risk.current_sl or risk.initial_sl) if risk else None,
            target=risk.target if risk else None,
            realized_pnl=round(leg.realized_pnl, 2),
        )


class RunOrderResult(BaseModel):
    leg_id: str
    intent: str = Field(description="entry or exit.")
    side: Side
    quantity: int
    symbol: str
    status: str = Field(description="pending if the sandbox never answered, else its status.")
    fill_price: float | None
    reason: str | None
    sandbox_order_id: str | None
    created_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    message: str


class StrategyRunResult(RunSummary):
    strategy_id: str
    name: str
    broker: str
    product: Product
    legs: list[RunLegResult]
    peak_mtm: float = Field(description="Highest P&L the run has reached, rupees.")
    trough_mtm: float = Field(description="Lowest P&L the run has reached, rupees.")
    lock_floor: float | None = Field(description="Locked profit, once the profit lock arms.")
    stops_at_entry: bool = Field(
        description="A leg's stop moved the others to entry; the combined stop loss is off."
    )
    orders: list[RunOrderResult]
    timeline: list[TimelineEntry] = Field(description="Latest 100 events, oldest first.")

    @classmethod
    def of_detail(cls, detail: RunDetail) -> "StrategyRunResult":
        run = detail.run
        return cls(
            **RunSummary.of(run).model_dump(),
            strategy_id=run.strategy_id,
            name=detail.strategy_name,
            broker=run.broker,
            product=run.product,
            legs=[RunLegResult.of(leg) for leg in run.legs],
            peak_mtm=round(run.peak_mtm, 2),
            trough_mtm=round(run.trough_mtm, 2),
            lock_floor=run.lock_floor,
            stops_at_entry=run.stops_at_entry,
            orders=[
                RunOrderResult(
                    leg_id=order.leg_id,
                    intent=order.intent,
                    side=order.side,
                    quantity=order.quantity,
                    symbol=order.symbol,
                    status=order.status,
                    fill_price=order.fill_price,
                    reason=order.reason,
                    sandbox_order_id=order.sandbox_order_id,
                    created_at=order.created_at.astimezone(EXCHANGE_TIMEZONE),
                )
                for order in detail.orders
            ],
            timeline=[
                TimelineEntry(
                    at=event.occurred_at.astimezone(EXCHANGE_TIMEZONE), message=event.message
                )
                for event in detail.events
            ],
        )


ALERT_PATH = "/webhooks/strategies"  # served by openticker-serve, outside /api/v1
ALERT_NEXT_STEP = (
    "Keep openticker-serve running and reachable at alert_url. TradingView (or any sender): "
    'POST {"action": "long_entry", "leg_id": "leg1"}, with action long_entry, long_exit, '
    "short_entry or short_exit, and leg_id, or symbol and exchange. ChartInk: set this URL as "
    "the scan's webhook and put BUY, SELL, SHORT or COVER in the scan's name. "
    "get_strategy_signals shows every alert and what came of it."
)


class WebhookResult(BaseModel):
    strategy_id: str
    name: str
    alert_path: str = Field(
        description="POST alerts here on openticker-serve. Carries the only copy of the "
        "token: keep it secret, and rotate_strategy_webhook again if it leaks."
    )
    alert_url: str | None = Field(
        description="The full URL, when OPENTICKER_PUBLIC_URL names where openticker-serve is "
        "reachable from the internet (a tunnel or reverse proxy)."
    )
    broker: str
    allowed_ips: list[str] = Field(description="Empty: any address may call it.")
    created_at: datetime
    next_step: str

    @classmethod
    def of(
        cls,
        stored: StoredStrategy,
        webhook: StoredWebhook,
        token: str,
        public_url: str | None,
        next_step: str,
    ) -> "WebhookResult":
        path = f"{ALERT_PATH}/{token}"
        return cls(
            strategy_id=stored.id,
            name=stored.name,
            alert_path=path,
            alert_url=public_url.rstrip("/") + path if public_url else None,
            broker=webhook.broker,
            allowed_ips=list(webhook.allowed_ips),
            created_at=webhook.created_at.astimezone(EXCHANGE_TIMEZONE),
            next_step=next_step,
        )


class WebhookInfo(BaseModel):
    broker: str
    allowed_ips: list[str]
    created_at: datetime


class SignalCallResult(BaseModel):
    received_at: datetime
    client_ip: str | None
    result: str = Field(
        description="accepted (written as commands), ignored (outside its schedule), refused "
        "(doesn't fit the strategy), locked (kill switch), forbidden (not in the allowlist)."
    )
    message: str
    alert_format: str | None = Field(description="chartink or json.")
    payload: str | None = Field(description="The body, with the token removed, capped.")
    commands: list[CommandResult] = Field(description="What the runner did with each signal.")


class StrategySignalsResult(BaseModel):
    strategy_id: str
    name: str
    locked: bool = Field(description="True while the kill switch is on: alerts are refused.")
    webhook: WebhookInfo | None = Field(description="Null when it has no alert URL.")
    calls: list[SignalCallResult] = Field(description="Newest first.")

    @classmethod
    def of(cls, detail: SignalsDetail) -> "StrategySignalsResult":
        webhook = detail.webhook
        return cls(
            strategy_id=detail.strategy.id,
            name=detail.strategy.name,
            locked=detail.strategy.locked,
            webhook=None
            if webhook is None
            else WebhookInfo(
                broker=webhook.broker,
                allowed_ips=list(webhook.allowed_ips),
                created_at=webhook.created_at.astimezone(EXCHANGE_TIMEZONE),
            ),
            calls=[
                SignalCallResult(
                    received_at=call.received_at.astimezone(EXCHANGE_TIMEZONE),
                    client_ip=call.client_ip,
                    result=call.result,
                    message=call.message,
                    alert_format=call.alert_format,
                    payload=call.payload,
                    commands=[
                        CommandResult.of(detail.commands[i])
                        for i in call.command_ids
                        if i in detail.commands
                    ],
                )
                for call in detail.calls
            ],
        )


class AlertResult(BaseModel):
    """The answer to an alert. Carries nothing the caller didn't send."""

    status: str = Field(description="accepted, ignored or the refusal.")
    message: str


# Hosted Python scripts (ADR 25 in docs/adr).


class ScriptScheduleDefinition(BaseModel):
    start_time: ExchangeTime = Field(description="HH:MM exchange time the script is started.")
    stop_time: ExchangeTime | None = Field(
        default=None,
        description="HH:MM exchange time it is stopped, whether it was started by hand or by "
        "the schedule. Omit to let it run until it exits by itself.",
    )
    weekdays: list[int] = Field(
        default=[0, 1, 2, 3, 4],
        description="Days it runs, 0 Monday to 6 Sunday. Days its exchange doesn't trade are "
        "always skipped.",
    )
    exchange: Exchange = Field(
        default=Exchange.NSE, description="Whose holidays and special sessions count."
    )

    def to_core(self) -> ScriptSchedule:
        try:
            return ScriptSchedule(
                start_time=self.start_time,
                stop_time=self.stop_time,
                weekdays=frozenset(self.weekdays),
                exchange=self.exchange,
            )
        except InvalidScriptError:
            raise
        except ValueError as exc:
            raise InvalidScriptError(str(exc)) from exc

    @classmethod
    def of(cls, schedule: ScriptSchedule) -> "ScriptScheduleDefinition":
        return cls(
            start_time=schedule.start_time,
            stop_time=schedule.stop_time,
            weekdays=sorted(schedule.weekdays),
            exchange=schedule.exchange,
        )


class ScriptRunResult(BaseModel):
    run_id: str
    status: ScriptRunStatus = Field(description="stopping: asked to stop, killed after 5s.")
    trigger: str = Field(description="Who started it: mcp, rest:<key>, schedule, recovery.")
    started_at: datetime
    pid: int | None
    stop_reason: ScriptStopReason | None = Field(
        description="exited (code 0), failed (an error or a signal), stopped (stop_script), "
        "schedule (stop_time), memory_limit, cpu_limit, log_limit, daemon_stopped, lost "
        "(gone when openticker-serve came back), start_failed."
    )
    stop_detail: str | None
    exit_code: int | None = Field(description="Negative: killed by that signal.")
    ended_at: datetime | None
    peak_memory_mb: float | None = Field(
        default=None,
        description="The most memory it was measured using, script and children; null: "
        "never measured.",
    )

    @classmethod
    def of(cls, run: ScriptRun) -> "ScriptRunResult":
        return cls(
            run_id=run.id,
            status=run.status,
            trigger=run.trigger,
            started_at=run.started_at.astimezone(EXCHANGE_TIMEZONE),
            pid=run.pid,
            stop_reason=run.stop_reason if run.status is ScriptRunStatus.ENDED else None,
            stop_detail=run.stop_detail,
            exit_code=run.exit_code,
            ended_at=_local(run.ended_at),
            peak_memory_mb=round(run.peak_memory_kb / 1024, 1)
            if run.peak_memory_kb is not None
            else None,
        )


class ScriptResult(BaseModel):
    script_id: str
    name: str
    size_bytes: int
    sha256: str = Field(description="Of the source, to tell versions apart.")
    schedule: ScriptScheduleDefinition | None = Field(
        description="Null: it runs only on start_script."
    )
    running: bool
    last_run: ScriptRunResult | None = Field(description="The latest run, going or ended.")
    updated_at: datetime
    next_step: str | None = None

    @classmethod
    def of(cls, summary: ScriptSummary, next_step: str | None = None) -> "ScriptResult":
        stored = summary.script
        return cls(
            script_id=stored.id,
            name=stored.name,
            size_bytes=stored.source_bytes,
            sha256=stored.source_sha256,
            schedule=ScriptScheduleDefinition.of(stored.schedule) if stored.schedule else None,
            running=summary.active is not None,
            last_run=ScriptRunResult.of(summary.last) if summary.last else None,
            updated_at=stored.updated_at.astimezone(EXCHANGE_TIMEZONE),
            next_step=next_step,
        )

    @classmethod
    def of_stored(cls, stored: StoredScript, next_step: str | None = None) -> "ScriptResult":
        return cls.of(ScriptSummary(stored, None, None), next_step)


class ScriptLimitsResult(BaseModel):
    memory_mb: int = Field(description="Resident memory of a run, script and children.")
    cpu_seconds: int = Field(description="CPU time of one run.")

    @classmethod
    def of(cls, limits: ScriptLimits) -> "ScriptLimitsResult":
        return cls(memory_mb=limits.memory_mb, cpu_seconds=limits.cpu_seconds)


class ScriptsResult(BaseModel):
    scripts: list[ScriptResult]
    limits: ScriptLimitsResult | None = Field(
        default=None,
        description="What every run is held to: SCRIPT_MEMORY_LIMIT_MB and SCRIPT_CPU_SECONDS.",
    )


class ScriptCommandInfo(BaseModel):
    command_id: int
    command: ScriptCommandKind
    status: ScriptCommandStatus = Field(
        description="pending: openticker-serve carries it out within about a second."
    )
    triggered_by: str
    outcome: str | None
    created_at: datetime

    @classmethod
    def of(cls, command: ScriptCommand) -> "ScriptCommandInfo":
        return cls(
            command_id=command.id,
            command=command.kind,
            status=command.status,
            triggered_by=command.triggered_by,
            outcome=command.outcome,
            created_at=command.created_at.astimezone(EXCHANGE_TIMEZONE),
        )


class ScriptDetailResult(BaseModel):
    script: ScriptResult
    runs: list[ScriptRunResult] = Field(description="Newest first.")
    commands: list[ScriptCommandInfo] = Field(
        description="Latest start and stop requests, newest first."
    )
    source: str | None = Field(description="Only when include_source was asked for.")

    @classmethod
    def of(cls, detail: ScriptDetail) -> "ScriptDetailResult":
        last = detail.runs[0] if detail.runs else None
        active = last if last is not None and last.ended_at is None else None
        return cls(
            script=ScriptResult.of(ScriptSummary(detail.script, active, last)),
            runs=[ScriptRunResult.of(run) for run in detail.runs],
            commands=[ScriptCommandInfo.of(command) for command in detail.commands],
            source=detail.source,
        )


class ScriptCommandResult(BaseModel):
    script_id: str
    command: ScriptCommandInfo
    next_step: str

    @classmethod
    def of(cls, command: ScriptCommand, next_step: str) -> "ScriptCommandResult":
        return cls(
            script_id=command.script_id, command=ScriptCommandInfo.of(command), next_step=next_step
        )


class ScriptLogsResult(BaseModel):
    script_id: str
    name: str
    run: ScriptRunResult
    lines: list[str] = Field(description="stdout and stderr together, oldest first.")
    truncated: bool = Field(description="True when earlier lines were left out.")

    @classmethod
    def of(cls, found: ScriptLog) -> "ScriptLogsResult":
        return cls(
            script_id=found.script.id,
            name=found.script.name,
            run=ScriptRunResult.of(found.run),
            lines=found.lines,
            truncated=found.truncated,
        )


class DeleteScriptResult(BaseModel):
    script_id: str
    deleted: bool


class ActiveRunResult(RunSummary):
    legs: list[RunLegResult]

    @classmethod
    def of(cls, run: Run) -> "ActiveRunResult":
        return cls(
            **RunSummary.of(run).model_dump(), legs=[RunLegResult.of(leg) for leg in run.legs]
        )


class ReviewBriefResult(BaseModel):
    job_id: str
    verdict: Verdict | None = Field(
        description="keep, change (one thing), retire, or not_yet (under 10 runs after "
        "costs); null when the answer leads with none."
    )
    summary: str
    harness: str
    trigger: str = Field(description="Who asked for it.")
    ended_at: datetime

    @classmethod
    def of(cls, job: AgentJob) -> "ReviewBriefResult":
        assert job.summary is not None and job.ended_at is not None
        return cls(
            job_id=job.id,
            verdict=verdict_of(job.summary),
            summary=job.summary,
            harness=job.harness,
            trigger=job.trigger,
            ended_at=job.ended_at.astimezone(EXCHANGE_TIMEZONE),
        )


StrategySummary.model_rebuild()


class DayPnlResult(BaseModel):
    trading_date: date
    net_pnl: float | None = Field(
        description="After charges: realized plus the open positions' change, less charges. "
        "None when an open position had no price."
    )
    realized_pnl: float = Field(description="Closed by the day's fills, before charges.")
    charges: float
    unrealized_pnl: float | None = Field(description="Open positions' change over the day.")
    fills: int
    complete: bool = Field(description="False when a fill didn't record what it realized.")
    estimated: bool = Field(description="Closing marks were the last prices known, not live.")
    live: bool = Field(description="Today, worked out now: not recorded until after the close.")

    @classmethod
    def of(cls, day: DayPnl, live: bool) -> "DayPnlResult":
        return cls(
            trading_date=day.trading_date,
            net_pnl=day.net_pnl,
            realized_pnl=day.realized_pnl,
            charges=day.charges,
            unrealized_pnl=day.unrealized_pnl,
            fills=day.fills,
            complete=day.complete,
            estimated=day.estimated,
            live=live,
        )


class PnlHistoryResult(BaseModel):
    days: list[DayPnlResult] = Field(
        description="Oldest first. Only days that were recorded (openticker-serve running after "
        "the close) and today."
    )

    @classmethod
    def of(cls, history: PnlHistory) -> "PnlHistoryResult":
        return cls(
            days=[
                DayPnlResult.of(day, live=day.trading_date == history.live) for day in history.days
            ]
        )


class MonthChargesResult(BaseModel):
    month: str = Field(description="YYYY-MM, exchange-local.")
    total: float
    by_type: dict[str, float] = Field(
        description="brokerage, transaction_tax, exchange, sebi, stamp_duty, gst. Covers fills "
        "that recorded each charge; `unitemized` is the rest."
    )
    unitemized: float
    fills: int

    @classmethod
    def of(cls, month: ChargeTotals) -> "MonthChargesResult":
        return cls(
            month=month.month,
            total=month.total,
            by_type=month.by_type,
            unitemized=month.unitemized,
            fills=month.fills,
        )


class ChargesSummaryResult(BaseModel):
    months: list[MonthChargesResult] = Field(description="Oldest first; months with fills only.")
    total: float


class WatchlistItemResult(BaseModel):
    symbol: str
    exchange: Exchange
    instrument_type: InstrumentType | None = Field(
        description="None when the instrument isn't in the instrument master; "
        "sync_instruments brings it back."
    )
    expiry: date | None
    strike: float | None
    lot_size: int | None


class WatchlistResult(BaseModel):
    watchlist_id: str = Field(description="Pass this to the other watchlist tools.")
    name: str
    items: list[WatchlistItemResult] = Field(
        description="In the order they were added; get_quotes prices them in one call."
    )

    @classmethod
    def of(
        cls, watchlist: Watchlist, instruments: Sequence[Instrument | None]
    ) -> "WatchlistResult":
        return cls(
            watchlist_id=watchlist.watchlist_id,
            name=watchlist.name,
            items=[
                WatchlistItemResult(
                    symbol=item.symbol,
                    exchange=Exchange(item.exchange),
                    instrument_type=found.instrument_type if found else None,
                    expiry=found.expiry if found else None,
                    strike=found.strike if found else None,
                    lot_size=found.lot_size if found else None,
                )
                for item, found in zip(watchlist.items, instruments, strict=True)
            ],
        )


class WatchlistsResult(BaseModel):
    watchlists: list[WatchlistResult] = Field(description="In the order they were made.")


class DeleteWatchlistResult(BaseModel):
    watchlist_id: str
    name: str
    deleted: bool
