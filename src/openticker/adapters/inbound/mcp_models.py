"""Tool result shapes. Each becomes the tool's `outputSchema`, so every field
carries a description the agent reads. Times are exchange-local (IST offset
included), matching the trading dates the tools take as input."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from openticker.core.options.models import GreeksModel, OptionChain, OptionQuote
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Bar,
    Exchange,
    Instrument,
    InstrumentType,
    Interval,
    Quote,
)


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


class AuditEntryResult(BaseModel):
    id: int
    occurred_at: datetime = Field(description="Exchange-local.")
    event_type: str
    triggered_by: str | None = Field(description="Which entry point caused it: mcp, rest, webhook.")
    details: dict[str, Any] = Field(description="The event's own fields.")


class AuditLogResult(BaseModel):
    entries: list[AuditEntryResult] = Field(description="Most recent first.")


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
