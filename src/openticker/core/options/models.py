"""Option chain value types. Conventions (ADR 16 in docs/adr): Black-76 on the
forward, theta per calendar day, vega and rho per one percentage point."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from openticker.ports.models import Instrument


class GreeksModel(StrEnum):
    IMPLIED = "implied"  # IV solved from the option's price, Greeks from that IV
    INTRINSIC = "intrinsic"  # no time value to solve from: delta from moneyness, the rest zero


@dataclass(frozen=True)
class Greeks:
    model: GreeksModel
    implied_volatility: float | None  # annualized, as a fraction (0.15 = 15%)
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass(frozen=True)
class OptionQuote:
    instrument: Instrument
    label: str  # ATM, ITM<n>, OTM<n>
    last_price: float | None  # None when the contract has no usable price
    open_interest: int | None
    greeks: Greeks | None  # None when last_price is None


@dataclass(frozen=True)
class ChainRow:
    strike: float
    call: OptionQuote | None
    put: OptionQuote | None


@dataclass(frozen=True)
class OptionChain:
    underlying: Instrument
    underlying_price: float
    forward_price: float
    expiry: date
    expires_at: datetime  # tz-aware UTC
    atm_strike: float
    interest_rate: float  # annualized, as a fraction
    rows: tuple[ChainRow, ...]  # ascending strike
