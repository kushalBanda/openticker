from datetime import date

import pytest

from openticker.core.strategies.legs import LegResolutionError, resolve_expiry, resolve_leg
from openticker.core.strategies.models import LegSpec, RelativeExpiry, StrikeSelector
from openticker.ports.models import InstrumentType, Side
from tests.fixtures.options import chain_contracts, future

TODAY = date(2026, 9, 22)  # a Tuesday, NIFTY's weekly expiry day
# Weeklies to the end of October; the last Tuesday of each month is the monthly.
NIFTY_EXPIRIES = [
    date(2026, 9, 22),
    date(2026, 9, 29),
    date(2026, 10, 6),
    date(2026, 10, 13),
    date(2026, 10, 27),
    date(2026, 12, 29),
]
MONTHLY_ONLY = [date(2026, 9, 29), date(2026, 10, 27), date(2026, 11, 24)]
EXPIRY = date(2026, 9, 29)
CHAIN = chain_contracts("NIFTY", EXPIRY, [24900.0, 24950.0, 25000.0, 25050.0, 25100.0])


def leg(option_type: InstrumentType, offset: int = 0, fixed: float | None = None) -> LegSpec:
    return LegSpec(
        side=Side.SELL,
        lots=1,
        option_type=option_type,
        expiry=RelativeExpiry.WEEKLY,
        strike=StrikeSelector(offset=offset, fixed_strike=fixed),
    )


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (RelativeExpiry.WEEKLY, date(2026, 9, 22)),
        (RelativeExpiry.NEXT_WEEK, date(2026, 9, 29)),
        (RelativeExpiry.MONTHLY, date(2026, 9, 29)),
        (RelativeExpiry.NEXT_MONTH, date(2026, 10, 27)),
    ],
)
def test_resolve_expiry_weekly_on_expiry_day(relative: RelativeExpiry, expected: date) -> None:
    assert resolve_expiry(relative, NIFTY_EXPIRIES, TODAY) == expected


def test_resolve_expiry_after_this_months_monthly_moves_to_next_month() -> None:
    assert resolve_expiry(RelativeExpiry.MONTHLY, NIFTY_EXPIRIES, date(2026, 9, 30)) == date(
        2026, 10, 27
    )


def test_resolve_expiry_monthly_only_underlying_refuses_weekly() -> None:
    assert resolve_expiry(RelativeExpiry.MONTHLY, MONTHLY_ONLY, TODAY) == date(2026, 9, 29)
    with pytest.raises(LegResolutionError, match="no weekly contracts"):
        resolve_expiry(RelativeExpiry.WEEKLY, MONTHLY_ONLY, TODAY)


def test_resolve_expiry_nothing_listed() -> None:
    with pytest.raises(LegResolutionError, match="sync_instruments"):
        resolve_expiry(RelativeExpiry.MONTHLY, [date(2026, 9, 1)], TODAY)


def test_resolve_leg_atm_otm_itm_by_option_type() -> None:
    price = 25010.0  # nearest listed strike is 25000

    assert resolve_leg(leg(InstrumentType.CE), price, CHAIN).instrument.strike == 25000.0
    otm_call = resolve_leg(leg(InstrumentType.CE, 2), price, CHAIN)
    otm_put = resolve_leg(leg(InstrumentType.PE, 2), price, CHAIN)
    itm_put = resolve_leg(leg(InstrumentType.PE, -1), price, CHAIN)

    assert (otm_call.instrument.strike, otm_call.label) == (25100.0, "OTM2")
    assert (otm_put.instrument.strike, otm_put.label) == (24900.0, "OTM2")
    assert (itm_put.instrument.strike, itm_put.label) == (25050.0, "ITM1")
    assert otm_put.instrument.instrument_type is InstrumentType.PE


def test_resolve_leg_atm_tie_goes_to_lower_strike() -> None:
    assert resolve_leg(leg(InstrumentType.CE), 25025.0, CHAIN).instrument.strike == 25000.0


def test_resolve_leg_missing_strike_raises() -> None:
    with pytest.raises(LegResolutionError, match="nearest listed are 24950, 25000"):
        resolve_leg(leg(InstrumentType.CE, fixed=24975.0), 25000.0, CHAIN)


def test_resolve_leg_offset_beyond_listed_strikes_raises() -> None:
    with pytest.raises(LegResolutionError, match="3 strikes out of the money"):
        resolve_leg(leg(InstrumentType.CE, 3), 25000.0, CHAIN)


def test_resolve_leg_fixed_strike() -> None:
    resolved = resolve_leg(leg(InstrumentType.PE, fixed=24950.0), 25000.0, CHAIN)

    assert (resolved.instrument.strike, resolved.label) == (24950.0, "OTM1")


def test_resolve_leg_future() -> None:
    fut = LegSpec(Side.BUY, 1, InstrumentType.FUT, RelativeExpiry.MONTHLY)

    resolved = resolve_leg(fut, 25000.0, [future("NIFTY", EXPIRY)])

    assert (resolved.instrument.symbol, resolved.label) == ("NIFTY29SEP26FUT", "FUT")
