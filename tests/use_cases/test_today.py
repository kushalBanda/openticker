from datetime import date, time, timedelta

import pytest

from openticker.events.subscribers.audit_log import record_event
from openticker.events.types import OrderFilled, StrategyStopped
from openticker.ports.models import Side
from openticker.use_cases.pnl_history import record_intraday_point
from openticker.use_cases.today import today
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.pnl_desk import MONDAY, Desk, at, new_desk


@pytest.fixture
def desk() -> Desk:
    return new_desk()


def test_first_visit_of_the_day_has_no_since(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)

    result = today(desk.sandbox, None, NO_HOLIDAYS, desk.now)

    assert result.trading_date == MONDAY and result.since is None
    assert result.figures.fills == 1 and result.market_open is True
    yesterday = today(desk.sandbox, at(MONDAY - timedelta(days=3), 11, 0), NO_HOLIDAYS, desk.now)
    assert yesterday.since is None  # a visit on another day


def test_since_counts_fills_names_the_kill_and_the_change(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    desk.now = at(MONDAY, 11, 2)
    record_intraday_point(desk.sandbox, desk.now)
    visit = desk.now
    desk.now = at(MONDAY, 11, 20)
    desk.trade(Side.BUY, 5)
    desk.trade(Side.SELL, 5)
    desk.market.price = 1010.0
    record_event(OrderFilled("o", "RELIANCE", "BUY", 5, 1000.0, "ui"))  # not named: counted
    record_event(
        StrategyStopped("stg_1", "run_1", "SBIN mean reversion", "kill", "killed by you", -2006.4)
    )
    desk.now = at(MONDAY, 11, 42)

    result = today(desk.sandbox, visit, NO_HOLIDAYS, desk.now)

    since = result.since
    assert since is not None and since.fills == 2
    assert [e.event_type for e in since.events] == ["StrategyStopped"]
    first = result.points[0]
    assert first.minute == time(11, 2)
    assert since.pnl_change == round((result.figures.net_pnl or 0) - first.net_pnl, 2)


def test_net_is_none_when_an_open_position_has_no_price(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    desk.market.prices["RELIANCE"] = 0.0  # no fillable price

    assert today(desk.sandbox, None, NO_HOLIDAYS, desk.now).figures.net_pnl is None


def test_a_weekend_shows_the_last_session(desk: Desk) -> None:
    saturday = at(date(2026, 9, 26), 11, 0)

    result = today(desk.sandbox, None, NO_HOLIDAYS, saturday)

    assert result.trading_date == date(2026, 9, 25) and result.market_open is False
