"""Tool result shapes. Each becomes the tool's `outputSchema`, so every field
carries a description the agent reads. Times are exchange-local (IST offset
included), matching the trading dates the tools take as input. The REST API
returns the same shapes (ADR 8 and ADR 17 in docs/adr)."""

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from openticker.core.calendar.models import MarketStatus
from openticker.core.options.models import GreeksModel, OptionChain, OptionQuote
from openticker.core.orders.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from openticker.core.risk.models import BreachReason
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
from openticker.use_cases.evaluate_risk import RiskCheck


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
