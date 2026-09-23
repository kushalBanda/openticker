"""A NIFTY market of weekly and monthly contracts, and strategy definitions over it."""

from datetime import UTC, date, datetime, time

from openticker.core.risk.models import LockMode, ProfitLock, StrategyLimits
from openticker.core.strategies.models import (
    Direction,
    Horizon,
    LegSpec,
    OptionsStrategySpec,
    RelativeExpiry,
    RiskValue,
    Schedule,
    SignalLeg,
    SignalStrategySpec,
    StrikeSelector,
)
from openticker.ports.models import Exchange, InstrumentType, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_LAST_PRICE
from tests.fixtures.options import NIFTY_INDEX, chain_contracts, future

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST, a NIFTY weekly expiry
WEEKLY = date(2026, 9, 22)
MONTHLY = date(2026, 9, 29)
NEXT_WEEKLY = date(2026, 10, 6)
NEXT_MONTH = date(2026, 10, 27)
STRIKES = [FAKE_LAST_PRICE + 50.0 * step for step in range(-3, 4)]  # ATM is the fake price

STRADDLE = OptionsStrategySpec(
    underlying="NIFTY 50",
    exchange=Exchange.NSE,
    legs=(
        LegSpec(Side.SELL, 1, InstrumentType.CE, RelativeExpiry.WEEKLY),
        LegSpec(Side.SELL, 1, InstrumentType.PE, RelativeExpiry.WEEKLY),
    ),
    horizon=Horizon.INTRADAY,
    schedule=Schedule(entry_time=time(9, 20), exit_time=time(15, 15)),
    limits=StrategyLimits(combined_stop_loss=3000.0, combined_target=5000.0),
)

# Every field set, so a storage round trip that drops one fails.
EVERYTHING = OptionsStrategySpec(
    underlying="NIFTY 50",
    exchange=Exchange.NSE,
    legs=(
        LegSpec(
            Side.SELL,
            2,
            InstrumentType.CE,
            RelativeExpiry.NEXT_WEEK,
            StrikeSelector(offset=2),
            stop_loss=RiskValue(30.0, percent=True),
            target=RiskValue(50.0, percent=True),
            trailing=RiskValue(10.0, percent=False),
        ),
        LegSpec(
            Side.BUY,
            1,
            InstrumentType.PE,
            RelativeExpiry.MONTHLY,
            StrikeSelector(fixed_strike=2450.0),
        ),
        LegSpec(Side.BUY, 1, InstrumentType.FUT, RelativeExpiry.NEXT_MONTH),
    ),
    horizon=Horizon.POSITIONAL,
    schedule=Schedule(
        entry_time=time(9, 45),
        exit_time=time(15, 20),
        weekdays=frozenset({1, 3}),
        exit_on_expiry=False,
    ),
    limits=StrategyLimits(
        combined_stop_loss=4000.0,
        combined_target=8000.0,
        lock_profit=ProfitLock(2000.0, 1000.0, LockMode.LOCK_AND_TRAIL, trail_step=500.0),
        stops_to_entry_on_leg_stop=True,
        daily_loss_limit=6000.0,
    ),
)


# A signal strategy with every field set.
SIGNAL_EVERYTHING = SignalStrategySpec(
    legs=(
        SignalLeg(
            "RELIANCE",
            Exchange.NSE,
            10,
            accepts=Direction.LONG_ONLY,
            stop_loss=RiskValue(2.0, percent=True),
            target=RiskValue(40.0, percent=False),
            trailing=RiskValue(1.5, percent=True),
        ),
        SignalLeg("NIFTY29SEP26FUT", Exchange.NFO, 130),
    ),
    horizon=Horizon.POSITIONAL,
    direction=Direction.BOTH,
    schedule=Schedule(
        entry_time=time(9, 30),
        exit_time=time(15, 10),
        weekdays=frozenset({0, 2, 4}),
        exit_on_expiry=False,
    ),
    limits=EVERYTHING.limits,
)


def list_nifty_market() -> None:
    upsert_instruments(
        [NIFTY_INDEX]
        + chain_contracts("NIFTY", WEEKLY, STRIKES)
        + chain_contracts("NIFTY", MONTHLY, STRIKES)
        + chain_contracts("NIFTY", NEXT_WEEKLY, STRIKES)
        + chain_contracts("NIFTY", NEXT_MONTH, STRIKES)
        + [future("NIFTY", MONTHLY), future("NIFTY", NEXT_MONTH)]
    )
