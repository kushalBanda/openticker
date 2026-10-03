from datetime import date, time, timedelta

import pytest

from openticker.core.pnl import DayFill, day_figures
from openticker.ports.models import Product, Side
from openticker.storage.sqlite import pnl_repo
from openticker.use_cases.pnl_history import (
    HistoryRangeError,
    get_charges_summary,
    get_pnl_history,
    record_daily_pnl,
    record_intraday_point,
)
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, Desk, at, new_desk


@pytest.fixture
def desk() -> Desk:
    return new_desk()


def test_day_figures_are_after_charges_and_open_change_since_the_close() -> None:
    figures = day_figures(
        [DayFill(1905.0, 120.0), DayFill(None, 66.4)], [5257.25, 800.0], carried=800.0
    )

    assert (figures.before_charges, figures.charges, figures.net_pnl) == (
        7162.25,
        186.4,
        6975.85,
    )  # the Dashboard mock's figures
    assert figures.fills == 2 and figures.complete is False
    assert day_figures([], [None], 0.0).net_pnl is None  # an open position without a price


def test_a_minute_point_and_the_day_agree(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    desk.market.price = 1010.0
    desk.now = at(MONDAY, 11, 42)

    point = record_intraday_point(desk.sandbox, desk.now)

    assert point is not None and point.minute == time(11, 42)
    assert point.unrealized_pnl == 100.0
    assert point.net_pnl == round(100.0 - point.charges, 2) and point.charges > 0
    assert pnl_repo.points_on(MONDAY) == [point]

    day = record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 15, 36))
    assert (day.net_pnl, day.open_value, day.estimated) == (point.net_pnl, 100.0, False)


def test_the_next_day_counts_only_its_own_move(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    desk.market.price = 1010.0
    record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 15, 36))
    desk.now = at(TUESDAY, 10, 0)
    desk.market.price = 1005.0

    history = get_pnl_history(MONDAY, TUESDAY, desk.sandbox, NO_HOLIDAYS, desk.now)

    monday, tuesday = history.days
    assert history.live == TUESDAY and monday.trading_date == MONDAY
    assert (tuesday.unrealized_pnl, tuesday.charges, tuesday.net_pnl) == (-50.0, 0.0, -50.0)


def test_recording_a_day_again_replaces_it(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 15, 36))
    desk.market.price = 1020.0
    record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 18, 0))

    [day] = pnl_repo.days_between(MONDAY, MONDAY)
    assert day.open_value == 200.0


def test_a_broker_that_cant_price_gives_an_estimated_day(desk: Desk) -> None:
    desk.trade(Side.BUY, 10)
    desk.market.price = 1010.0
    desk.now = at(MONDAY, 15, 29)
    record_intraday_point(desk.sandbox, desk.now)
    desk.market.down = True

    day = record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 15, 36))

    assert day.estimated is True
    assert (day.unrealized_pnl, day.open_value) == (100.0, 100.0)  # the last point's marks


def test_old_minute_points_are_pruned(desk: Desk) -> None:
    desk.trade(Side.BUY, 1)
    desk.now = at(MONDAY - timedelta(days=35), 10, 0)
    record_intraday_point(desk.sandbox, desk.now)

    record_daily_pnl(MONDAY, desk.sandbox, at(MONDAY, 15, 36))

    assert pnl_repo.points_on(MONDAY - timedelta(days=35)) == []


def test_ranges_are_bounded(desk: Desk) -> None:
    with pytest.raises(HistoryRangeError, match="at most 400 days"):
        get_pnl_history(date(2025, 1, 1), MONDAY, desk.sandbox, NO_HOLIDAYS, desk.now)
    with pytest.raises(HistoryRangeError, match="before"):
        get_charges_summary(TUESDAY, MONDAY)


def test_charges_are_summed_by_month_and_by_charge(desk: Desk) -> None:
    desk.trade(Side.BUY, 10, Product.MIS)
    desk.trade(Side.SELL, 10, Product.MIS)

    [month] = get_charges_summary(date(2026, 9, 1), date(2026, 9, 30))

    assert (month.month, month.fills, month.unitemized) == ("2026-09", 2, 0.0)
    assert month.total > 0
    assert round(sum(month.by_type.values()), 2) == month.total
