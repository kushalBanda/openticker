from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from openticker.core.options.underlyings import UnsupportedUnderlyingError
from openticker.core.strategies.legs import LegResolutionError
from openticker.core.strategies.models import (
    InvalidStrategyError,
    LegSpec,
    RelativeExpiry,
    StrikeSelector,
)
from openticker.ports.models import Exchange, InstrumentType, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from openticker.use_cases.strategies.define import (
    UnknownStrategyError,
    create_strategy,
    delete_strategy,
    get_strategy,
    preview_strategy,
    update_strategy,
)
from tests.fixtures.fake_broker import FAKE_LAST_PRICE, FakeBrokerPort
from tests.fixtures.options import NIFTY_INDEX
from tests.fixtures.strategies import (
    EVERYTHING,
    MONTHLY,
    NEXT_MONTH,
    NOW,
    STRADDLE,
    WEEKLY,
    list_nifty_market,
)


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def test_preview_resolves_an_atm_straddle_to_real_contracts() -> None:
    stored = create_strategy("nifty straddle", STRADDLE, NOW)

    preview = preview_strategy(stored.id, FakeBrokerPort(), NOW)

    assert preview.underlying_price == FAKE_LAST_PRICE
    assert [(leg.leg_id, leg.instrument.symbol, leg.label) for leg in preview.legs] == [
        ("leg1", "NIFTY22SEP262500CE", "ATM"),
        ("leg2", "NIFTY22SEP262500PE", "ATM"),
    ]
    assert [leg.quantity for leg in preview.legs] == [65, 65]
    assert preview.net_premium == 2 * FAKE_LAST_PRICE * 65  # both sold: a credit


def test_preview_resolves_offsets_fixed_strikes_and_futures() -> None:
    stored = create_strategy("everything", EVERYTHING, NOW)

    legs = preview_strategy(stored.id, FakeBrokerPort(), NOW).legs

    assert [(leg.instrument.symbol, leg.label, leg.quantity) for leg in legs] == [
        ("NIFTY29SEP262600CE", "OTM2", 130),
        ("NIFTY29SEP262450PE", "OTM1", 65),
        ("NIFTY27OCT26FUT", "FUT", 65),
    ]


def test_preview_after_the_weekly_expires_moves_to_the_next() -> None:
    stored = create_strategy("nifty straddle", STRADDLE, NOW)
    after_close = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)  # 16:00 IST

    legs = preview_strategy(stored.id, FakeBrokerPort(), after_close).legs

    assert {leg.instrument.expiry for leg in legs} == {MONTHLY}
    assert WEEKLY < MONTHLY < NEXT_MONTH


def test_preview_names_the_leg_that_cannot_be_resolved() -> None:
    too_far = replace(
        STRADDLE,
        legs=(
            STRADDLE.legs[0],
            LegSpec(Side.BUY, 1, InstrumentType.PE, RelativeExpiry.WEEKLY, StrikeSelector(5)),
        ),
    )
    stored = create_strategy("too far", too_far, NOW)

    with pytest.raises(LegResolutionError, match=r"leg2 \(NIFTY PE\): 5 strikes out of"):
        preview_strategy(stored.id, FakeBrokerPort(), NOW)


def test_create_checks_name_and_underlying() -> None:
    with pytest.raises(InvalidStrategyError, match="name"):
        create_strategy(" leading space", STRADDLE, NOW)
    with pytest.raises(UnknownInstrumentError):
        create_strategy("x", replace(STRADDLE, underlying="NOT AN INDEX"), NOW)
    upsert_instruments([replace(NIFTY_INDEX, symbol="NIFTY IT", token="1")])
    with pytest.raises(UnsupportedUnderlyingError, match="no options listed"):
        create_strategy("x", replace(STRADDLE, underlying="NIFTY IT", exchange=Exchange.NSE), NOW)


def test_unknown_ids_say_how_to_find_one() -> None:
    later = NOW + timedelta(minutes=1)
    for call in (
        lambda: get_strategy("stg_missing"),
        lambda: update_strategy("stg_missing", "x", STRADDLE, later),
        lambda: delete_strategy("stg_missing", later),
        lambda: preview_strategy("stg_missing", FakeBrokerPort(), later),
    ):
        with pytest.raises(UnknownStrategyError, match="list_strategies"):
            call()
