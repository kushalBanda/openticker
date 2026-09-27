"""The Strategies mock's five strategies for the web app's end-to-end server:
what each is doing now, months of ended runs with fills that paid charges,
reviews, and a signal strategy's alerts. History is dated June to August, so
the Trades page's week and month keep only their own fills."""

import random
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, Harness
from openticker.core.risk.models import StrategyLimits, StrategyStopReason
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
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, InstrumentType, Product, Side
from openticker.storage.sqlite import agent_jobs_repo, runs_repo, signals_repo, strategies_repo
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import SandboxOrderRow, SandboxTradeRow
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.strategies.control import rotate_webhook, schedule_strategy
from tests.fixtures.strategies import STRADDLE

# The straddle with the mock's 30% stop on each leg.
STRADDLE_E2E = replace(
    STRADDLE,
    legs=tuple(replace(leg, stop_loss=RiskValue(30.0, percent=True)) for leg in STRADDLE.legs),
)
TREND = SignalStrategySpec(
    legs=(
        SignalLeg(
            "NIFTY27OCT26FUT",
            Exchange.NFO,
            75,
            accepts=Direction.LONG_ONLY,
            stop_loss=RiskValue(0.6, percent=True),
            target=RiskValue(1.5, percent=True),
        ),
    ),
    horizon=Horizon.POSITIONAL,
    direction=Direction.LONG_ONLY,
    limits=StrategyLimits(daily_loss_limit=5000.0),
)
BREAKOUT = SignalStrategySpec(
    legs=(SignalLeg("RELIANCE", Exchange.NSE, 50, accepts=Direction.LONG_ONLY),),
    horizon=Horizon.INTRADAY,
    direction=Direction.LONG_ONLY,
    schedule=Schedule(exit_time=time(15, 10)),
)
REVERSION = SignalStrategySpec(
    legs=(SignalLeg("SBIN", Exchange.NSE, 200),),
    horizon=Horizon.INTRADAY,
    limits=StrategyLimits(daily_loss_limit=2000.0),
)
CONDOR = OptionsStrategySpec(
    underlying="NIFTY BANK",
    exchange=Exchange.NSE,
    legs=(
        LegSpec(Side.SELL, 1, InstrumentType.CE, RelativeExpiry.MONTHLY, StrikeSelector(offset=4)),
        LegSpec(Side.BUY, 1, InstrumentType.CE, RelativeExpiry.MONTHLY, StrikeSelector(offset=8)),
        LegSpec(Side.SELL, 1, InstrumentType.PE, RelativeExpiry.MONTHLY, StrikeSelector(offset=4)),
        LegSpec(Side.BUY, 1, InstrumentType.PE, RelativeExpiry.MONTHLY, StrikeSelector(offset=8)),
    ),
    horizon=Horizon.INTRADAY,
    schedule=Schedule(entry_time=time(9, 20), exit_time=time(15, 15), weekdays=frozenset({0})),
    limits=StrategyLimits(combined_stop_loss=4000.0, combined_target=3000.0),
)


def _rate(symbol: str, exchange: Exchange) -> float:
    """Charges per rupee of turnover, roughly: futures, options, cash."""
    if symbol.endswith("FUT"):
        return 0.0001
    return 0.001 if exchange is Exchange.NFO else 0.0003


# (symbol, exchange, side, units, entry price) per leg of a past run.
PastLeg = tuple[str, Exchange, Side, int, float]


def _trading_days(first: date, last: date, weekdays: frozenset[int]) -> list[date]:
    days, day = [], first
    while day <= last:
        if day.weekday() in weekdays:
            days.append(day)
        day += timedelta(days=1)
    return days


def _history(
    strategy_id: str,
    legs: Sequence[PastLeg],
    days: Sequence[date],
    drift: float,
    swing: float,
    rng: random.Random,
    product: str,
) -> None:
    """One ended run a day: entered 09:20, out by 15:15, each leg's exit a
    random move around `drift` (rupees per unit, in the leg's favour)."""
    reasons = [StrategyStopReason.SCHEDULE] * 6 + [
        StrategyStopReason.COMBINED_TARGET,
        StrategyStopReason.COMBINED_STOP_LOSS,
        StrategyStopReason.LEGS_CLOSED,
    ]
    with Session(get_engine()) as session, session.begin():
        for n, day in enumerate(days):
            entered = datetime.combine(day, time(9, 20), EXCHANGE_TIMEZONE).astimezone(UTC)
            exited = entered + timedelta(hours=rng.uniform(1.0, 5.9))
            run_id = f"run_e2e_{strategy_id[-6:]}_{n:03d}"
            run_legs = []
            for index, (symbol, exchange, side, units, entry) in enumerate(legs, 1):
                move = rng.gauss(drift, swing)
                out = round(max(0.05, entry - move if side is Side.SELL else entry + move), 2)
                run_legs.append(
                    RunLeg(
                        f"leg{index}",
                        symbol,
                        exchange,
                        side,
                        units,
                        LegStatus.CLOSED,
                        entry_price=entry,
                        entered_at=entered,
                        exit_price=out,
                        exit_reason="schedule",
                    )
                )
                for k, (at, fill_side, price) in enumerate(
                    (
                        (entered, side, entry),
                        (exited, Side.BUY if side is Side.SELL else Side.SELL, out),
                    )
                ):
                    order_id = f"{run_id}-{index}-{k}"
                    turnover = price * units
                    session.add(
                        SandboxOrderRow(
                            order_id=order_id,
                            placed_at=at.replace(tzinfo=None),
                            exchange=exchange.value,
                            symbol=symbol,
                            side=fill_side.value,
                            quantity=units,
                            product=product,
                            order_type="MARKET",
                            status="FILLED",
                            fill_price=price,
                            reason=None,
                            triggered_by=f"strategy:{strategy_id}",
                            strategy_id=strategy_id,
                            run_id=run_id,
                        )
                    )
                    session.add(
                        SandboxTradeRow(
                            order_id=order_id,
                            filled_at=at.replace(tzinfo=None),
                            exchange=exchange.value,
                            symbol=symbol,
                            side=fill_side.value,
                            quantity=units,
                            price=price,
                            product=product,
                            strategy_id=strategy_id,
                            run_id=run_id,
                            charges=round(20.0 + turnover * _rate(symbol, exchange), 2),
                            expected_price=round(price - 0.05 if k else price + 0.05, 2),
                            realized_pnl=None,
                        )
                    )
            runs_repo.insert_run(
                session,
                Run(
                    id=run_id,
                    strategy_id=strategy_id,
                    broker="fake",
                    product=Product(product),
                    status=RunStatus.ENDED,
                    trigger="schedule",
                    started_at=entered,
                    legs=tuple(run_legs),
                    stop_reason=rng.choice(reasons),
                    ended_at=exited,
                ),
            )


def _review(
    strategy_id: str, at: datetime, summary: str, trigger: str = "schedule: 20 runs"
) -> None:
    with write_transaction() as session:
        job = agent_jobs_repo.add_job(
            session, AgentJobKind.REVIEW, strategy_id, Harness.CLAUDE, trigger, at
        )
        agent_jobs_repo.end_job(
            session,
            job.id,
            AgentJobEndReason.FINISHED,
            "exited with code 0",
            at + timedelta(minutes=3),
            exit_code=0,
            summary=summary,
            cost_usd=0.42,
        )


def seed_strategies(now: Callable[[], datetime], straddle_id: str, trend_id: str) -> dict[str, str]:
    """History and reviews for the two running strategies (seeded by the
    caller with their open runs), then the other three. Their ids, by name."""
    rng = random.Random(21)
    summer = _trading_days(date(2026, 6, 1), date(2026, 8, 31), frozenset(range(5)))
    today = now()

    _history(
        straddle_id,
        [
            ("NIFTY27AUG2624800CE", Exchange.NFO, Side.SELL, 75, 142.0),
            ("NIFTY27AUG2624800PE", Exchange.NFO, Side.SELL, 75, 131.0),
        ],
        summer,
        drift=4.0,
        swing=12.0,
        rng=rng,
        product="MIS",
    )
    _review(
        straddle_id,
        today - timedelta(days=3),
        "Keep. The edge survives charges: 59% of runs win after costs, and the average "
        "win is larger than the average loss. Losses cluster on expiry day after 11:00; "
        "watch that before the next review.",
    )
    _review(straddle_id, today - timedelta(days=30), "Not yet: 8 of 10 runs after costs.")

    _history(
        trend_id,
        [("NIFTY27AUG26FUT", Exchange.NFO, Side.BUY, 75, 24650.0)],
        summer[::3],
        drift=9.0,
        swing=60.0,
        rng=rng,
        product="NRML",
    )
    _review(
        trend_id,
        today - timedelta(hours=2),
        "Change one thing: exit by 15:00. Net is positive after costs, but runs held past "
        "15:00 gave back a third of it. Ask for it as a new strategy to run side by side.",
        trigger="ui",
    )
    for minutes, result, message in (
        (12, "accepted", "long_entry: entered 75"),
        (40, "accepted", "exit: exited 75"),
        (70, "ignored", "short_entry ignored: the strategy is long only"),
    ):
        signals_repo.record_call(
            trend_id,
            today - timedelta(minutes=minutes),
            "52.89.214.238",
            result,
            message,
            alert_format="tradingview",
            payload='{"action": "buy", "alert": "NIFTY 15m EMA cross"}',
        )

    breakout = insert_strategy("RELIANCE breakout", BREAKOUT, today)
    _history(
        breakout.id,
        [("RELIANCE", Exchange.NSE, Side.BUY, 50, 2870.0)],
        summer[1::4],
        drift=3.0,
        swing=18.0,
        rng=rng,
        product="MIS",
    )
    rotate_webhook(breakout.id, "fake", [], today)
    rotate_webhook(trend_id, "fake", [], today)

    condor = insert_strategy("BANKNIFTY iron condor", CONDOR, today)
    mondays = _trading_days(date(2026, 6, 1), date(2026, 8, 31), frozenset({0}))
    _history(
        condor.id,
        [
            ("BANKNIFTY27AUG2654000CE", Exchange.NFO, Side.SELL, 35, 210.0),
            ("BANKNIFTY27AUG2654800CE", Exchange.NFO, Side.BUY, 35, 88.0),
            ("BANKNIFTY27AUG2651600PE", Exchange.NFO, Side.SELL, 35, 196.0),
            ("BANKNIFTY27AUG2650800PE", Exchange.NFO, Side.BUY, 35, 81.0),
        ],
        mondays,
        drift=0.8,
        swing=9.0,
        rng=rng,
        product="MIS",
    )
    schedule_strategy(condor.id, "fake")
    _review(
        condor.id,
        today - timedelta(days=7),
        "Retire. Net after costs is negative over 14 runs: four legs pay four sets of "
        "charges, which eat the credit.",
    )

    reversion = insert_strategy("SBIN mean reversion", REVERSION, today)
    _history(
        reversion.id,
        [("SBIN", Exchange.NSE, Side.BUY, 200, 812.0)],
        summer[2::4],
        drift=-0.9,
        swing=4.0,
        rng=rng,
        product="MIS",
    )
    with write_transaction() as session:
        strategies_repo.set_locked(session, reversion.id, True)

    return {
        "RELIANCE breakout": breakout.id,
        "BANKNIFTY iron condor": condor.id,
        "SBIN mean reversion": reversion.id,
    }
