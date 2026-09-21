from datetime import UTC, date, datetime, timedelta

import pytest

from openticker.core.options.chain import (
    ChainInputError,
    atm_strike,
    build_option_chain,
    expires_at,
    forward_price,
    strike_label,
    strikes_around,
    years_to_expiry,
)
from openticker.core.options.greeks import MIN_YEARS_TO_EXPIRY, black76_price
from openticker.core.options.models import GreeksModel
from openticker.ports.models import InstrumentType, Quote
from tests.fixtures.options import NIFTY_INDEX, chain_contracts, option

CE, PE = InstrumentType.CE, InstrumentType.PE
EXPIRY = date(2026, 9, 29)
NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # 09:30 IST
STRIKES = [24800.0, 24900.0, 25000.0, 25100.0, 25200.0]


def test_expiry_is_1530_exchange_time() -> None:
    assert expires_at(EXPIRY) == datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


def test_years_to_expiry_floors_near_expiry_and_raises_after() -> None:
    minute_before = expires_at(EXPIRY) - timedelta(minutes=1)

    assert years_to_expiry(EXPIRY, minute_before) == MIN_YEARS_TO_EXPIRY
    with pytest.raises(ChainInputError, match="already expired"):
        years_to_expiry(EXPIRY, expires_at(EXPIRY))


def test_atm_is_nearest_strike_and_ties_go_lower() -> None:
    assert atm_strike(25040, STRIKES) == 25000
    assert atm_strike(25050, STRIKES) == 25000
    assert atm_strike(25051, STRIKES) == 25100


def test_labels_mirror_for_calls_and_puts() -> None:
    assert strike_label(CE, 24800, 25000, STRIKES) == "ITM2"
    assert strike_label(PE, 24800, 25000, STRIKES) == "OTM2"
    assert strike_label(CE, 25100, 25000, STRIKES) == "OTM1"
    assert strike_label(PE, 25100, 25000, STRIKES) == "ITM1"
    assert strike_label(PE, 25000, 25000, STRIKES) == "ATM"


def test_strikes_around_clips_at_the_ends() -> None:
    assert strikes_around(24900, STRIKES, 2) == [24800, 24900, 25000, 25100]


def test_forward_uses_parity_and_falls_back_without_both_legs() -> None:
    assert forward_price(25000, 180.0, 120.0, 0.02, 0.0, fallback=24990) == 25060
    assert forward_price(25000, 180.0, None, 0.02, 0.0, fallback=24990) == 24990


def _quotes(forward: float, volatility: float, now: datetime) -> dict[str, Quote]:
    years = years_to_expiry(EXPIRY, now)
    return {
        contract.symbol: Quote(
            contract,
            black76_price(
                contract.instrument_type, forward, contract.strike or 0, years, 0, volatility
            ),
            now,
            open_interest=1000,
        )
        for contract in chain_contracts("NIFTY", EXPIRY, STRIKES)
    }


def test_chain_recovers_forward_above_spot_and_flat_volatility() -> None:
    # Futures trade 60 above spot; pricing the chain off spot would skew every IV.
    chain = build_option_chain(
        NIFTY_INDEX,
        25000,
        chain_contracts("NIFTY", EXPIRY, STRIKES),
        _quotes(25060, 0.14, NOW),
        NOW,
    )

    assert chain.atm_strike == 25000
    assert chain.forward_price == pytest.approx(25060)
    assert [row.strike for row in chain.rows] == STRIKES
    for row in chain.rows:
        for leg in (row.call, row.put):
            assert leg is not None and leg.greeks is not None
            assert leg.greeks.model is GreeksModel.IMPLIED
            assert leg.greeks.implied_volatility == pytest.approx(0.14, abs=1e-4)
            assert leg.open_interest == 1000


def test_unpriced_contract_appears_without_greeks() -> None:
    quotes = _quotes(25060, 0.14, NOW)
    quotes[option("NIFTY", EXPIRY, 25200, CE).symbol] = Quote(
        option("NIFTY", EXPIRY, 25200, CE), 0.0, NOW
    )
    del quotes[option("NIFTY", EXPIRY, 24800, PE).symbol]

    chain = build_option_chain(
        NIFTY_INDEX, 25000, chain_contracts("NIFTY", EXPIRY, STRIKES), quotes, NOW
    )

    assert chain.rows[-1].call is not None
    assert (chain.rows[-1].call.last_price, chain.rows[-1].call.greeks) == (None, None)
    assert chain.rows[0].put is not None and chain.rows[0].put.open_interest is None


def test_mixed_expiries_are_rejected() -> None:
    contracts = [option("NIFTY", EXPIRY, 25000, CE), option("NIFTY", date(2026, 10, 6), 25000, PE)]

    with pytest.raises(ChainInputError, match="one expiry"):
        build_option_chain(NIFTY_INDEX, 25000, contracts, {}, NOW)
