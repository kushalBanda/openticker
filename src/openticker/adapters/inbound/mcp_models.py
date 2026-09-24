"""Tool result shapes. Each becomes the tool's `outputSchema`, so every field
carries a description the agent reads. Times are exchange-local (IST offset
included), matching the trading dates the tools take as input. The REST API
returns the same shapes (ADR 8 and ADR 17 in docs/adr)."""

import json
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, WithJsonSchema

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
    ScriptRun,
    ScriptRunStatus,
    ScriptSchedule,
    ScriptStopReason,
)
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
    Exchange,
    Funds,
    Instrument,
    InstrumentType,
    Interval,
    Position,
    Product,
    Quote,
    Side,
)
from openticker.storage.sqlite.audit_repo import AuditEntry
from openticker.storage.sqlite.scripts_repo import StoredScript
from openticker.storage.sqlite.signals_repo import StoredWebhook
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.use_cases.evaluate_risk import RiskCheck
from openticker.use_cases.scripts.manage import ScriptDetail, ScriptLog, ScriptSummary
from openticker.use_cases.strategies.control import RunDetail, SignalsDetail
from openticker.use_cases.strategies.define import StrategyPreview

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

    @classmethod
    def of(cls, quote: Quote) -> "QuoteResult":
        return cls(
            symbol=quote.instrument.symbol,
            exchange=quote.instrument.exchange,
            last_price=quote.last_price,
            as_of=quote.as_of.astimezone(EXCHANGE_TIMEZONE),
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


class AuditEntryResult(BaseModel):
    id: int
    occurred_at: datetime = Field(description="Exchange-local.")
    event_type: str
    triggered_by: str | None = Field(description="Which entry point caused it: mcp, rest, webhook.")
    details: dict[str, Any] = Field(description="The event's own fields.")

    @classmethod
    def of(cls, entry: AuditEntry) -> "AuditEntryResult":
        return cls(
            id=entry.id,
            occurred_at=entry.occurred_at.astimezone(EXCHANGE_TIMEZONE),
            event_type=entry.event_type,
            triggered_by=entry.triggered_by,
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

    @classmethod
    def of(cls, chain: OptionChain, expiries: list[date], now: datetime) -> "OptionChainResult":
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


class CancelOrderResult(BaseModel):
    order_id: str
    status: OrderStatus = Field(description="CANCELLED, or the status that kept it from being.")
    reason: str | None

    @classmethod
    def of(cls, order_id: str, result: OrderResult) -> "CancelOrderResult":
        return cls(order_id=order_id, status=result.status, reason=result.reason)


class PositionResult(BaseModel):
    symbol: str
    exchange: Exchange
    product: Product
    quantity: int = Field(description="Net and signed: negative is short, 0 is closed.")
    average_price: float
    last_price: float | None = Field(description="None when no fresh price was available.")
    unrealized_pnl: float | None
    realized_pnl: float

    @classmethod
    def of(cls, position: Position) -> "PositionResult":
        return cls(
            symbol=position.instrument.symbol,
            exchange=position.instrument.exchange,
            product=position.product,
            quantity=position.quantity,
            average_price=round(position.average_price, 4),
            last_price=position.last_price,
            unrealized_pnl=(
                round(position.unrealized_pnl, 2) if position.unrealized_pnl is not None else None
            ),
            realized_pnl=round(position.realized_pnl, 2),
        )


class PositionsResult(BaseModel):
    positions: list[PositionResult]
    total_unrealized_pnl: float | None = Field(
        description="None when any open position has no current price."
    )
    total_realized_pnl: float

    @classmethod
    def of(cls, positions: Sequence[Position], include_closed: bool) -> "PositionsResult":
        shown = [position for position in positions if include_closed or position.quantity]
        unrealized = [position.unrealized_pnl for position in shown]
        return cls(
            positions=[PositionResult.of(position) for position in shown],
            total_unrealized_pnl=(
                None
                if any(value is None for value in unrealized)
                else round(sum(value or 0.0 for value in unrealized), 2)
            ),
            total_realized_pnl=round(sum(position.realized_pnl for position in positions), 2),
        )


class FundsResult(BaseModel):
    total_capital: float = Field(description="Virtual starting capital.")
    available_cash: float = Field(description="Capital - used margin + realized P&L.")
    used_margin: float
    realized_pnl: float

    @classmethod
    def of(cls, funds: Funds) -> "FundsResult":
        return cls(
            total_capital=funds.total_capital,
            available_cash=round(funds.available_cash, 2),
            used_margin=round(funds.used_margin, 2),
            realized_pnl=round(funds.realized_pnl, 2),
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
    triggered_by: str

    @classmethod
    def of(cls, order: Order) -> "OrderbookEntryResult":
        return cls(
            order_id=order.order_id,
            placed_at=order.placed_at.astimezone(EXCHANGE_TIMEZONE),
            symbol=order.instrument.symbol,
            exchange=order.instrument.exchange,
            side=order.side,
            quantity=order.quantity,
            product=order.product,
            order_type=order.order_type,
            price=order.price,
            trigger_price=order.trigger_price,
            status=order.status,
            fill_price=order.fill_price,
            reason=order.reason,
            triggered_by=order.triggered_by,
        )


class OrderbookResult(BaseModel):
    orders: list[OrderbookEntryResult] = Field(description="Most recent first.")

    @classmethod
    def of(cls, orders: Sequence[Order]) -> "OrderbookResult":
        return cls(orders=[OrderbookEntryResult.of(order) for order in orders])


class TradeResult(BaseModel):
    order_id: str
    filled_at: datetime = Field(description="Exchange-local.")
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float = Field(description="Fill price.")
    value: float = Field(description="price x quantity.")
    product: Product
    triggered_by: str
    strategy_id: str | None
    run_id: str | None

    @classmethod
    def of(cls, trade: Trade) -> "TradeResult":
        return cls(
            order_id=trade.order_id,
            filled_at=trade.filled_at.astimezone(EXCHANGE_TIMEZONE),
            symbol=trade.instrument.symbol,
            exchange=trade.instrument.exchange,
            side=trade.side,
            quantity=trade.quantity,
            price=trade.price,
            value=round(trade.price * trade.quantity, 2),
            product=trade.product,
            triggered_by=trade.triggered_by,
            strategy_id=trade.strategy_id,
            run_id=trade.run_id,
        )


class TradebookResult(BaseModel):
    trades: list[TradeResult] = Field(description="Newest first.")
    since: datetime = Field(description="Start of today, exchange-local.")

    @classmethod
    def of(cls, trades: Sequence[Trade], since: datetime) -> "TradebookResult":
        return cls(
            trades=[TradeResult.of(trade) for trade in trades],
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
    updated_at: datetime

    @classmethod
    def of(cls, stored: StoredStrategy) -> "StrategySummary":
        return cls(
            strategy_id=stored.id,
            name=stored.name,
            kind="signal" if isinstance(stored.spec, SignalStrategySpec) else "options",
            underlying=", ".join(leg.symbol for leg in stored.spec.legs)
            if isinstance(stored.spec, SignalStrategySpec)
            else stored.spec.underlying,
            legs=len(stored.spec.legs),
            horizon=stored.spec.horizon,
            locked=stored.locked,
            scheduled=stored.scheduled_broker is not None,
            updated_at=stored.updated_at.astimezone(EXCHANGE_TIMEZONE),
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


class ScriptsResult(BaseModel):
    scripts: list[ScriptResult]


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
