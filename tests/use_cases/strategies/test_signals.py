import json
from datetime import datetime, time, timedelta

import pytest

from openticker.core.strategies.models import (
    Horizon,
    InvalidStrategyError,
    Schedule,
    SignalLeg,
    SignalStrategySpec,
)
from openticker.core.strategies.runs import CommandKind, CommandStatus
from openticker.core.strategies.signals import Alert, SignalAction, read_alert
from openticker.ports.models import Exchange
from openticker.storage.sqlite import runs_repo, signals_repo
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.strategies.control import (
    disable_webhook,
    get_signals,
    release_kill_switch,
    request_kill,
    request_start,
    rotate_webhook,
    schedule_strategy,
)
from openticker.use_cases.strategies.define import (
    StrategyKindError,
    create_strategy,
    preview_strategy,
    update_strategy,
)
from openticker.use_cases.strategies.signals import (
    SIGNALS_PER_MINUTE,
    SignalOutcome,
    SignalResult,
    accept_signal,
    ip_allowed,
)
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort
from tests.fixtures.strategies import NOW, STRADDLE, list_nifty_market
from tests.fixtures.strategy_desk import CE, LOT

SPEC = SignalStrategySpec(
    legs=(SignalLeg("RELIANCE", Exchange.NSE, 10), SignalLeg(CE, Exchange.NFO, LOT)),
    horizon=Horizon.INTRADAY,
)
IP = "52.89.214.238"


@pytest.fixture
def strategy_id() -> str:
    upsert_instruments([FAKE_INSTRUMENT])
    list_nifty_market()
    return create_strategy("alerts", SPEC, NOW).id


@pytest.fixture
def token(strategy_id: str) -> str:
    return rotate_webhook(strategy_id, "fake", [], NOW)[2]


def _send(token: str, payload: object, ip: str | None = IP, now: datetime = NOW) -> SignalOutcome:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return accept_signal(token, ip, body, now)


def test_an_alert_is_written_as_signal_commands_and_recorded(strategy_id: str, token: str) -> None:
    outcome = _send(token, {"action": "long_entry", "leg_id": "leg2"})

    assert outcome.result is SignalResult.ACCEPTED
    assert outcome.message == "leg2 long_entry queued"
    [command] = runs_repo.commands_by_id(list(outcome.command_ids)).values()
    assert (command.kind, command.leg_id, command.action, command.broker) == (
        CommandKind.SIGNAL,
        "leg2",
        SignalAction.LONG_ENTRY,
        "fake",
    )
    assert (command.triggered_by, command.status) == ("webhook", CommandStatus.PENDING)
    [call] = signals_repo.list_calls(strategy_id, 5)
    assert (call.result, call.client_ip, call.alert_format, call.command_ids) == (
        "accepted",
        IP,
        "json",
        outcome.command_ids,
    )


def test_a_chartink_alert_keeps_no_copy_of_the_url(strategy_id: str, token: str) -> None:
    outcome = _send(
        token,
        {
            "stocks": "RELIANCE,INFY",
            "trigger_prices": "2500,1500",
            "scan_name": "BUY breakout",
            "scan_url": "breakout",
            "alert_name": "breakout",
            "webhook_url": f"https://example.org/webhooks/strategies/{token}",
            "secret_key": "hunter2",
        },
    )

    assert outcome.result is SignalResult.ACCEPTED
    assert outcome.message == ("leg1 long_entry queued; not legs of this strategy, skipped: INFY")
    [call] = signals_repo.list_calls(strategy_id, 5)
    assert call.alert_format == "chartink" and call.payload is not None
    assert token not in call.payload and "hunter2" not in call.payload
    stored = json.loads(call.payload)
    assert (stored["webhook_url"], stored["secret_key"], stored["stocks"]) == (
        "[redacted]",
        "[redacted]",
        "RELIANCE,INFY",
    )


def test_unknown_malformed_rotated_and_disabled_tokens_get_one_answer(
    strategy_id: str, token: str
) -> None:
    fresh = rotate_webhook(strategy_id, "fake", [], NOW)[2]

    answers = {
        _send(bad, {"action": "long_entry", "leg_id": "leg1"}).message
        for bad in (token, "otw_" + "x" * 43, "nonsense", fresh + "/")
    }
    assert answers == {"unknown alert URL: it was never made, or has been rotated"}
    assert _send(fresh, {"action": "long_exit", "leg_id": "leg1"}).result is SignalResult.ACCEPTED
    disable_webhook(strategy_id)
    assert _send(fresh, {"action": "long_exit", "leg_id": "leg1"}).result is SignalResult.UNKNOWN
    # Unknown tokens are never recorded: only the one call that got through was.
    assert len(signals_repo.list_calls(strategy_id, 10)) == 1


def test_a_killed_strategy_refuses_alerts_until_released(strategy_id: str, token: str) -> None:
    request_kill(strategy_id, "mcp", NOW)

    locked = _send(token, {"action": "long_entry", "leg_id": "leg1"})

    assert (locked.result, locked.message) == (SignalResult.LOCKED, "locked by its kill switch")
    assert not locked.command_ids
    [kill] = runs_repo.recent_commands(strategy_id, 5)
    with write_transaction() as session:  # as the runner does once it has flattened
        runs_repo.settle_command(session, kill.id, CommandStatus.DONE, "nothing was running", NOW)
    release_kill_switch(strategy_id)
    assert _send(token, {"action": "long_entry", "leg_id": "leg1"}).result is SignalResult.ACCEPTED


def test_a_locked_strategy_answers_locked_before_reading_the_body(
    strategy_id: str, token: str
) -> None:
    request_kill(strategy_id, "mcp", NOW)

    assert _send(token, b"garbage").result is SignalResult.LOCKED


def test_a_kill_while_an_alert_is_read_writes_no_commands(
    strategy_id: str, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def killed_meanwhile(payload: dict[str, object], spec: SignalStrategySpec) -> Alert:
        request_kill(strategy_id, "mcp", NOW)
        return read_alert(payload, spec)

    monkeypatch.setattr("openticker.use_cases.strategies.signals.read_alert", killed_meanwhile)

    outcome = _send(token, {"action": "long_entry", "leg_id": "leg1"})

    assert (outcome.result, outcome.command_ids) == (SignalResult.LOCKED, ())
    assert [c.kind for c in runs_repo.recent_commands(strategy_id, 5)] == [CommandKind.KILL]


def test_the_allowlist_admits_only_its_addresses(strategy_id: str) -> None:
    token = rotate_webhook(strategy_id, "fake", [IP, "10.0.0.0/8"], NOW)[2]
    alert = {"action": "long_entry", "leg_id": "leg1"}

    assert _send(token, alert, IP).result is SignalResult.ACCEPTED
    assert _send(token, alert, "10.4.5.6").result is SignalResult.ACCEPTED
    assert _send(token, alert, "::ffff:52.89.214.238").result is SignalResult.ACCEPTED
    forbidden = _send(token, alert, "8.8.8.8")
    assert (forbidden.result, forbidden.message) == (
        SignalResult.FORBIDDEN,
        "8.8.8.8 is not in this alert URL's allowlist",
    )
    assert _send(token, alert, None).result is SignalResult.FORBIDDEN
    assert ip_allowed("anything", ())
    assert not ip_allowed("not an address", (IP,))


def test_alerts_over_the_rate_limit_are_refused_unrecorded(strategy_id: str, token: str) -> None:
    for _ in range(SIGNALS_PER_MINUTE):
        signals_repo.record_call(strategy_id, NOW, IP, "ignored", "filler")

    over = _send(token, {"action": "long_entry", "leg_id": "leg1"})
    later = _send(
        token, {"action": "long_entry", "leg_id": "leg1"}, now=NOW + timedelta(seconds=61)
    )

    assert over.result is SignalResult.RATE_LIMITED
    assert later.result is SignalResult.ACCEPTED
    assert len(signals_repo.list_calls(strategy_id, 200)) == SIGNALS_PER_MINUTE + 1


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"not json", "the body is not JSON"),
        (b"[1, 2]", "the body must be a JSON object"),
        (b"\xff", "the body is not JSON"),
        (b" " * 20_000, "the body is larger than 16384 bytes"),
        (json.dumps({"action": "sideways", "leg_id": "leg1"}).encode(), "'action' must be"),
    ],
)
def test_a_body_that_is_not_an_alert_is_refused_and_recorded(
    strategy_id: str, token: str, body: bytes, why: str
) -> None:
    outcome = _send(token, body)

    assert outcome.result is SignalResult.REFUSED and outcome.message.startswith(why)
    assert signals_repo.list_calls(strategy_id, 5)[0].result == "refused"


def test_alerts_outside_the_schedule_are_ignored(strategy_id: str) -> None:
    windowed = create_strategy(
        "windowed",
        SignalStrategySpec(
            legs=SPEC.legs, horizon=Horizon.INTRADAY, schedule=Schedule(entry_time=time(10, 0))
        ),
        NOW,
    )
    token = rotate_webhook(windowed.id, "fake", [], NOW)[2]  # NOW is 09:30 IST

    early = _send(token, {"stocks": "RELIANCE", "scan_name": "BUY"})
    exit_early = _send(token, {"stocks": "RELIANCE", "scan_name": "SELL"})

    assert (early.result, early.message) == (
        SignalResult.IGNORED,
        "leg1 long_entry ignored: before entry_time 10:00",
    )
    assert not early.command_ids
    assert exit_early.result is SignalResult.ACCEPTED


def test_the_webhook_is_for_signal_strategies_only(strategy_id: str) -> None:
    options = create_strategy("straddle", STRADDLE, NOW)

    with pytest.raises(StrategyKindError, match="is an options strategy"):
        rotate_webhook(options.id, "fake", [], NOW)
    with pytest.raises(StrategyKindError, match="nothing to start"):
        request_start(strategy_id, "fake", "mcp", NOW)
    with pytest.raises(StrategyKindError, match="nothing to schedule"):
        schedule_strategy(strategy_id, "fake")
    with pytest.raises(StrategyKindError, match="nothing to resolve"):
        preview_strategy(strategy_id, FakeBrokerPort(), NOW)
    with pytest.raises(StrategyKindError, match="a strategy keeps its kind"):
        update_strategy(strategy_id, "alerts", STRADDLE, NOW)
    with pytest.raises(StrategyKindError, match="a strategy keeps its kind"):
        update_strategy(options.id, "straddle", SPEC, NOW)


def test_rotate_checks_the_allowlist(strategy_id: str) -> None:
    with pytest.raises(InvalidStrategyError, match="'example.org' is not an IP address"):
        rotate_webhook(strategy_id, "fake", ["example.org"], NOW)
    with pytest.raises(InvalidStrategyError, match="at most 20"):
        rotate_webhook(strategy_id, "fake", [IP] * 21, NOW)

    _, webhook, token = rotate_webhook(strategy_id, "fake", [" 10.1.2.3/8 "], NOW)
    assert webhook.allowed_ips == ("10.0.0.0/8",)
    assert token.startswith("otw_") and len(token) > 40


def test_get_signals_shows_each_alert_and_what_the_runner_did(strategy_id: str, token: str) -> None:
    accepted = _send(token, {"action": "long_entry", "leg_id": "leg1"})
    _send(token, b"nope")

    detail = get_signals(strategy_id, 10)

    assert detail.webhook is not None and detail.webhook.broker == "fake"
    assert [call.result for call in detail.calls] == ["refused", "accepted"]
    assert list(detail.commands) == list(accepted.command_ids)


def test_a_signal_strategy_names_real_contracts_in_whole_lots(strategy_id: str) -> None:
    with pytest.raises(InvalidStrategyError, match=r"leg1 \(INFY NSE\) is not in the instrument"):
        create_strategy(
            "bad",
            SignalStrategySpec(
                legs=(SignalLeg("INFY", Exchange.NSE, 1),), horizon=Horizon.INTRADAY
            ),
            NOW,
        )
    with pytest.raises(InvalidStrategyError, match="not a whole number of lots of 65"):
        create_strategy(
            "bad",
            SignalStrategySpec(legs=(SignalLeg(CE, Exchange.NFO, 60),), horizon=Horizon.INTRADAY),
            NOW,
        )
    with pytest.raises(InvalidStrategyError, match=r"expired on 2026-09-22"):
        create_strategy(
            "bad",
            SignalStrategySpec(legs=(SignalLeg(CE, Exchange.NFO, LOT),), horizon=Horizon.INTRADAY),
            NOW + timedelta(days=1),
        )
