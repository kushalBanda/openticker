from datetime import UTC, date, datetime, time

from openticker.adapters.inbound.daemon.pnl_loop import PnlLoop
from openticker.ports.models import EXCHANGE_TIMEZONE, Side
from openticker.storage.sqlite import pnl_repo
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.pnl_desk import MONDAY, Desk, at, new_desk


def _loop(desk: Desk) -> PnlLoop:
    return PnlLoop(lambda: desk.sandbox, lambda: NO_HOLIDAYS, lambda: desk.now)


def test_one_point_per_minute_in_session_only() -> None:
    desk = new_desk()
    desk.trade(Side.BUY, 1)
    loop = _loop(desk)

    for moment in (at(MONDAY, 9, 0), at(MONDAY, 9, 15), at(MONDAY, 9, 15), at(MONDAY, 9, 16)):
        desk.now = moment
        loop.step()

    assert [p.minute for p in pnl_repo.points_on(MONDAY)] == [time(9, 15), time(9, 16)]


def test_the_day_is_recorded_once_after_1535() -> None:
    desk = new_desk()
    desk.trade(Side.BUY, 1)
    loop = _loop(desk)
    desk.now = at(MONDAY, 15, 34)
    loop.step()
    assert not pnl_repo.day_recorded(MONDAY)

    desk.now = at(MONDAY, 15, 36)
    loop.step()
    desk.market.price = 2000.0
    desk.now = at(MONDAY, 16, 0)
    loop.step()

    [day] = pnl_repo.days_between(MONDAY, MONDAY)
    assert day.open_value == 0.0  # recorded at 15:36, not again at 16:00


def test_weekends_record_nothing() -> None:
    desk = new_desk()
    desk.trade(Side.BUY, 1)
    saturday = date(2026, 9, 26)
    desk.now = datetime.combine(saturday, time(15, 40), EXCHANGE_TIMEZONE).astimezone(UTC)

    _loop(desk).step()

    assert not pnl_repo.day_recorded(saturday)
    assert pnl_repo.points_on(saturday) == []
