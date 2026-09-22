import pytest

from openticker.core.risk.models import BreachReason
from openticker.ports.models import Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.evaluate_risk import evaluate_risk
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def test_entering_now_with_a_stop_above_the_price_breaches_and_warns() -> None:
    check = evaluate_risk(
        PricedBroker(100.0), "RELIANCE", "NSE", Side.BUY, 10, None, 105.0, None, None
    )

    assert check.last_price == 100.0
    assert check.decision.breached and check.decision.reason is BreachReason.STOP_LOSS
    assert check.warnings


def test_sensible_settings_do_not_breach() -> None:
    check = evaluate_risk(
        PricedBroker(100.0), "RELIANCE", "NSE", Side.SELL, 10, 102.0, 110.0, 90.0, None
    )

    assert not check.decision.breached
    assert check.decision.unrealized_pnl == 20.0
    assert check.decision.exit_side is None
