from datetime import UTC, datetime, time

import pytest

from openticker.core.strategies.models import (
    Direction,
    Horizon,
    InvalidStrategyError,
    RiskValue,
    Schedule,
    SignalLeg,
    SignalStrategySpec,
)
from openticker.core.strategies.signals import (
    AlertFormat,
    Move,
    Signal,
    SignalAction,
    SignalRefused,
    read_alert,
    signal_move,
    window_note,
)
from openticker.ports.models import Exchange, Side

SBIN = SignalLeg("SBIN", Exchange.NSE, 10)
TCS = SignalLeg("TCS", Exchange.NSE, 5, accepts=Direction.LONG_ONLY)
BSE_SBIN = SignalLeg("SBIN", Exchange.BSE, 10)
SPEC = SignalStrategySpec(legs=(SBIN, TCS, BSE_SBIN), horizon=Horizon.INTRADAY)
TUESDAY_10 = datetime(2026, 9, 22, 4, 30, tzinfo=UTC)  # 10:00 IST


def _one(payload: dict[str, object], spec: SignalStrategySpec = SPEC) -> Signal:
    alert = read_alert(payload, spec)
    assert alert.format is AlertFormat.JSON
    return alert.signals[0]


def test_a_json_alert_names_its_leg_by_id_or_by_symbol() -> None:
    assert _one({"action": "long_entry", "leg_id": "leg2"}) == Signal(
        "leg2", SignalAction.LONG_ENTRY
    )
    assert _one({"action": " SHORT_EXIT ", "symbol": "sbin"}) == Signal(
        "leg1", SignalAction.SHORT_EXIT
    )
    assert _one({"action": "short_entry", "symbol": "SBIN", "exchange": "bse"}) == Signal(
        "leg3", SignalAction.SHORT_ENTRY
    )


def test_a_json_alert_is_read_as_json_whatever_else_it_carries() -> None:
    assert _one({"action": "long_entry", "leg_id": "leg1", "stocks": "TCS"}) == Signal(
        "leg1", SignalAction.LONG_ENTRY
    )


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"action": "buy", "leg_id": "leg1"}, "'action' must be one of long_entry"),
        ({"action": 1, "leg_id": "leg1"}, "'action' must be one of"),
        ({"leg_id": "leg1"}, "'action' must be one of"),
        ({"action": "long_entry", "leg_id": "leg9"}, "no leg 'leg9'; this strategy's legs are"),
        ({"action": "long_entry"}, "name the leg"),
        ({"action": "long_entry", "symbol": "INFY"}, "no leg trades INFY"),
        ({"action": "long_entry", "symbol": "TCS", "exchange": "BSE"}, "no leg trades TCS"),
    ],
)
def test_a_json_alert_that_names_no_leg_is_refused(payload: dict[str, object], why: str) -> None:
    with pytest.raises(SignalRefused, match=why):
        read_alert(payload, SPEC)


@pytest.mark.parametrize(
    ("scan", "action"),
    [
        ("Breakout BUY", SignalAction.LONG_ENTRY),
        ("sell on weakness", SignalAction.LONG_EXIT),
        ("SHORT-15m", SignalAction.SHORT_ENTRY),
        ("cover shorts", SignalAction.SHORT_EXIT),
    ],
)
def test_a_chartink_scan_name_says_the_action(scan: str, action: SignalAction) -> None:
    alert = read_alert({"stocks": "SBIN", "scan_name": scan, "trigger_prices": "800"}, SPEC)

    assert alert.format is AlertFormat.CHARTINK
    assert alert.signals == (Signal("leg1", action),)


@pytest.mark.parametrize("scan", ["momentum scan", "BUY or SELL", "short cover", "BUYERS"])
def test_a_chartink_scan_name_must_hold_exactly_one_action_word(scan: str) -> None:
    with pytest.raises(SignalRefused, match="exactly one of BUY, SELL, SHORT or COVER"):
        read_alert({"stocks": "SBIN", "scan_name": scan}, SPEC)


def test_chartink_stocks_that_are_not_legs_are_skipped() -> None:
    alert = read_alert({"stocks": "infy, SBIN,TCS,SBIN,", "scan_name": "BUY"}, SPEC)

    # SBIN once, and the first leg trading it; INFY isn't a leg.
    assert alert.signals == (
        Signal("leg1", SignalAction.LONG_ENTRY),
        Signal("leg2", SignalAction.LONG_ENTRY),
    )
    assert alert.skipped == ("INFY",)
    with pytest.raises(SignalRefused, match="none of INFY, HDFC is a leg"):
        read_alert({"stocks": "INFY,HDFC", "scan_name": "BUY"}, SPEC)


def test_the_strategy_direction_and_the_leg_refuse_the_other_side() -> None:
    long_only = SignalStrategySpec(
        legs=(SBIN,), horizon=Horizon.INTRADAY, direction=Direction.LONG_ONLY
    )

    with pytest.raises(SignalRefused, match="this strategy is long_only; a short alert"):
        read_alert({"action": "short_entry", "leg_id": "leg1"}, long_only)
    with pytest.raises(SignalRefused, match="this strategy is long_only; a short alert"):
        read_alert({"action": "short_exit", "leg_id": "leg1"}, long_only)
    with pytest.raises(SignalRefused, match="leg2 accepts long_only alerts; a short one"):
        read_alert({"stocks": "SBIN,TCS", "scan_name": "SHORT"}, SPEC)
    assert _one({"action": "long_exit", "leg_id": "leg1"}, long_only).action.long


def test_entries_wait_for_entry_time_and_weekdays_but_exits_do_not() -> None:
    schedule = Schedule(entry_time=time(10, 0), exit_time=time(15, 0), weekdays=frozenset({1}))
    before = datetime(2026, 9, 22, 4, 29, tzinfo=UTC)  # Tuesday 09:59 IST

    assert window_note(schedule, SignalAction.LONG_ENTRY, before) == "before entry_time 10:00"
    assert window_note(schedule, SignalAction.LONG_EXIT, before) is None
    assert window_note(schedule, SignalAction.SHORT_ENTRY, TUESDAY_10) is None
    wednesday = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    assert window_note(schedule, SignalAction.LONG_ENTRY, wednesday) == (
        "Wednesday is not one of its weekdays"
    )
    assert window_note(schedule, SignalAction.SHORT_EXIT, wednesday) is None


def test_nothing_is_taken_from_exit_time() -> None:
    schedule = Schedule(exit_time=time(15, 0))
    at_exit = datetime(2026, 9, 22, 9, 30, tzinfo=UTC)  # 15:00 IST

    assert window_note(schedule, SignalAction.LONG_EXIT, at_exit) == "after exit_time 15:00"
    assert window_note(schedule, SignalAction.LONG_ENTRY, at_exit) == "after exit_time 15:00"
    assert window_note(Schedule(), SignalAction.LONG_ENTRY, at_exit) is None


@pytest.mark.parametrize(
    ("action", "held", "move", "why"),
    [
        (SignalAction.LONG_ENTRY, None, Move.ENTER, "entering long"),
        (SignalAction.LONG_ENTRY, Side.BUY, Move.NONE, "already long"),
        (SignalAction.LONG_ENTRY, Side.SELL, Move.FLIP, "closing the short, then entering long"),
        (SignalAction.SHORT_ENTRY, Side.BUY, Move.FLIP, "closing the long, then entering short"),
        (SignalAction.SHORT_ENTRY, Side.SELL, Move.NONE, "already short"),
        (SignalAction.LONG_EXIT, Side.BUY, Move.EXIT, "exiting the long"),
        (SignalAction.LONG_EXIT, Side.SELL, Move.NONE, "no long position to exit"),
        (SignalAction.SHORT_EXIT, None, Move.NONE, "no short position to exit"),
        (SignalAction.SHORT_EXIT, Side.SELL, Move.EXIT, "exiting the short"),
    ],
)
def test_what_a_signal_does_to_a_leg(
    action: SignalAction, held: Side | None, move: Move, why: str
) -> None:
    assert signal_move(action, held) == (move, why)


def test_a_signal_strategy_refuses_legs_it_could_never_trade() -> None:
    with pytest.raises(InvalidStrategyError, match="each leg trades a different contract"):
        SignalStrategySpec(
            legs=(SBIN, SignalLeg("sbin", Exchange.NSE, 1)), horizon=Horizon.INTRADAY
        )
    with pytest.raises(InvalidStrategyError, match=r"leg1 \(TCS\) accepts long_only alerts"):
        SignalStrategySpec(legs=(TCS,), horizon=Horizon.INTRADAY, direction=Direction.SHORT_ONLY)
    with pytest.raises(InvalidStrategyError, match="shares can't be held short overnight"):
        SignalStrategySpec(legs=(SBIN,), horizon=Horizon.POSITIONAL)
    with pytest.raises(InvalidStrategyError, match="squared off at 15:15"):
        SignalStrategySpec(
            legs=(SBIN,), horizon=Horizon.INTRADAY, schedule=Schedule(exit_time=time(15, 20))
        )
    with pytest.raises(InvalidStrategyError, match="1 to 10 legs"):
        SignalStrategySpec(legs=(), horizon=Horizon.INTRADAY)
    # Shares held long overnight, and futures short overnight, are fine.
    SignalStrategySpec(legs=(TCS,), horizon=Horizon.POSITIONAL)
    SignalStrategySpec(
        legs=(SignalLeg("NIFTY29SEP26FUT", Exchange.NFO, 65),), horizon=Horizon.POSITIONAL
    )
    SignalStrategySpec(legs=(SBIN,), horizon=Horizon.POSITIONAL, direction=Direction.LONG_ONLY)


def test_a_signal_leg_refuses_impossible_percentages_only_on_sides_it_takes() -> None:
    with pytest.raises(InvalidStrategyError, match="quantity must be at least 1"):
        SignalLeg("SBIN", Exchange.NSE, 0)
    with pytest.raises(InvalidStrategyError, match="names its symbol"):
        SignalLeg(" ", Exchange.NSE, 1)
    with pytest.raises(InvalidStrategyError, match="a long's stop loss in percent"):
        SignalLeg("SBIN", Exchange.NSE, 1, stop_loss=RiskValue(100.0, percent=True))
    with pytest.raises(InvalidStrategyError, match="a short's target in percent"):
        SignalLeg("SBIN", Exchange.NSE, 1, target=RiskValue(100.0, percent=True))
    SignalLeg(
        "SBIN",
        Exchange.NSE,
        1,
        accepts=Direction.SHORT_ONLY,
        stop_loss=RiskValue(150.0, percent=True),
    )
    SignalLeg(
        "SBIN", Exchange.NSE, 1, accepts=Direction.LONG_ONLY, target=RiskValue(150.0, percent=True)
    )
