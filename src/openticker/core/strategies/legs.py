"""Resolve a leg chosen relative to the market to one listed contract. Pure:
the caller passes in the listed expiries, contracts and the underlying's
price. Rules: ADR 20 in docs/adr."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from openticker.core.options.chain import atm_strike, strike_label
from openticker.core.strategies.models import LegSpec, RelativeExpiry
from openticker.ports.models import Instrument, InstrumentType

# Listed expiries this close together mean the underlying has weekly contracts.
_WEEKLY_GAP = timedelta(days=7)


class LegResolutionError(LookupError):
    """No listed contract matches the leg. Never resolved to a neighbour."""


@dataclass(frozen=True)
class ResolvedLeg:
    instrument: Instrument
    label: str  # ATM, ITM2, OTM1, or FUT


def resolve_expiry(expiry: RelativeExpiry, expiries: Sequence[date], today: date) -> date:
    """`expiries` are the listed option (or futures) expiries; those before
    `today` are ignored, and today's counts until the caller drops it."""
    listed = sorted({listed for listed in expiries if listed >= today})
    if not listed:
        raise LegResolutionError("no unexpired contracts listed; run sync_instruments")
    if expiry in (RelativeExpiry.WEEKLY, RelativeExpiry.NEXT_WEEK):
        if not any(later - earlier <= _WEEKLY_GAP for earlier, later in pairwise(listed)):
            raise LegResolutionError(
                "this underlying has no weekly contracts; use monthly or next_month"
            )
        index = 0 if expiry is RelativeExpiry.WEEKLY else 1
        if index >= len(listed):
            raise LegResolutionError("no expiry after the nearest one is listed yet")
        return listed[index]
    months = sorted({(listed_on.year, listed_on.month) for listed_on in listed})
    index = 0 if expiry is RelativeExpiry.MONTHLY else 1
    if index >= len(months):
        raise LegResolutionError("no contracts listed for the month after the nearest")
    year, month = months[index]
    return max(
        listed_on for listed_on in listed if (listed_on.year, listed_on.month) == (year, month)
    )


def resolve_leg(
    leg: LegSpec, underlying_price: float, contracts: Sequence[Instrument]
) -> ResolvedLeg:
    """`contracts` are the listed contracts of the leg's resolved expiry."""
    matching = [contract for contract in contracts if contract.instrument_type is leg.option_type]
    if leg.option_type is InstrumentType.FUT:
        if not matching:
            raise LegResolutionError("no futures contract listed for that expiry")
        return ResolvedLeg(matching[0], "FUT")
    by_strike = {contract.strike: contract for contract in matching if contract.strike is not None}
    strikes = sorted(by_strike)
    if not strikes:
        raise LegResolutionError(f"no {leg.option_type} contracts listed for that expiry")
    atm = atm_strike(underlying_price, strikes)
    selector = leg.strike
    if selector is not None and selector.fixed_strike is not None:
        strike = selector.fixed_strike
        if strike not in by_strike:
            raise LegResolutionError(
                f"strike {strike:g} {leg.option_type} is not listed; nearest listed are "
                f"{', '.join(f'{listed:g}' for listed in _nearest(strikes, strike))}"
            )
    else:
        offset = selector.offset if selector is not None else 0
        # Out of the money is above ATM for a call and below it for a put.
        step = offset if leg.option_type is InstrumentType.CE else -offset
        index = strikes.index(atm) + step
        if not 0 <= index < len(strikes):
            raise LegResolutionError(
                f"{_describe(offset)} {leg.option_type} from ATM {atm:g} is beyond the listed "
                f"strikes ({strikes[0]:g} to {strikes[-1]:g})"
            )
        strike = strikes[index]
    return ResolvedLeg(by_strike[strike], strike_label(leg.option_type, strike, atm, strikes))


def _describe(offset: int) -> str:
    return f"{abs(offset)} strikes {'out of' if offset > 0 else 'in'} the money"


def _nearest(strikes: Sequence[float], strike: float) -> list[float]:
    return sorted(sorted(strikes, key=lambda listed: abs(listed - strike))[:2])
