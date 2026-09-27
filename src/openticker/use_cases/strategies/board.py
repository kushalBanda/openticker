"""Every strategy with what it is doing now: the web app's strategies list
(ADR 30 in docs/adr) and `list_strategies`. Its state, the open run, today's
net and all-time net after costs (ADR 28, 29), and its latest review."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from openticker.core.agents.jobs import AgentJob
from openticker.core.calendar.models import MarketCalendar
from openticker.core.strategies.ledger import ledger_totals
from openticker.core.strategies.models import OptionsStrategySpec, SignalStrategySpec
from openticker.core.strategies.runs import CommandKind, Run, RunStatus
from openticker.core.strategies.schedule import next_entry
from openticker.ports.models import EXCHANGE_TIMEZONE, InstrumentType
from openticker.storage.sqlite import (
    agent_jobs_repo,
    instruments_repo,
    runs_repo,
    signals_repo,
    strategies_repo,
)
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.strategies_repo import StoredStrategy
from openticker.use_cases.strategies.ledger import ledger_runs


class StrategyState(StrEnum):
    KILLED = "killed"  # the kill switch is on
    RUNNING = "running"  # a run is open, or a start is waiting for the daemon
    LISTENING = "listening"  # a signal strategy with an alert URL and nothing open
    SCHEDULED = "scheduled"  # enters on its schedule
    STOPPED = "stopped"


class Segment(StrEnum):
    EQ = "EQ"
    FUT = "FUT"
    OPT = "OPT"


@dataclass(frozen=True)
class BoardRow:
    strategy: StoredStrategy
    state: StrategyState
    segments: tuple[Segment, ...]  # what it trades, in EQ, FUT, OPT order
    active_run: Run | None
    pending: CommandKind | None  # the oldest request the daemon hasn't carried out
    next_entry: datetime | None  # when scheduled
    today_net: float  # runs started today and the open run: realized less charges
    net_pnl: float  # every run after costs (ADR 29)
    runs: int  # every run it has had
    judged: int  # runs after costs
    wins: int
    max_drawdown: float
    last_run_at: datetime | None  # when the newest run started
    has_alert_url: bool  # a signal strategy's
    review: AgentJob | None  # the newest review that answered


def strategy_board(calendar: MarketCalendar, now: datetime) -> list[BoardRow]:
    """By name, as list_strategies has always listed them."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    reviews = agent_jobs_repo.latest_answers()
    rows = []
    for stored in strategies_repo.list_strategies():
        runs = ledger_runs(stored.id)
        active = next((r.run for r in runs if r.run.status is not RunStatus.ENDED), None)
        pending = _pending(stored.id)
        starting = active is None and pending is CommandKind.START
        alert_url = (
            isinstance(stored.spec, SignalStrategySpec)
            and signals_repo.find_webhook(stored.id) is not None
        )
        totals = ledger_totals(runs)
        rows.append(
            BoardRow(
                strategy=stored,
                state=_state(stored, active is not None or starting, alert_url),
                segments=_segments(stored),
                active_run=active,
                pending=pending,
                next_entry=next_entry(stored.spec.schedule, stored.spec.exchange, calendar, now)
                if isinstance(stored.spec, OptionsStrategySpec) and stored.scheduled_broker
                else None,
                today_net=round(
                    sum(
                        r.net_pnl
                        for r in runs
                        if r.run.status is not RunStatus.ENDED
                        or r.run.started_at.astimezone(EXCHANGE_TIMEZONE).date() == today
                    ),
                    2,
                ),
                net_pnl=totals.net_pnl,
                runs=len(runs),
                judged=totals.runs,
                wins=totals.wins,
                max_drawdown=totals.max_drawdown,
                last_run_at=runs[0].run.started_at if runs else None,
                has_alert_url=alert_url,
                review=reviews.get(stored.id),
            )
        )
    return rows


def _state(stored: StoredStrategy, running: bool, alert_url: bool) -> StrategyState:
    if stored.locked:
        return StrategyState.KILLED
    if running:
        return StrategyState.RUNNING
    if isinstance(stored.spec, SignalStrategySpec):
        return StrategyState.LISTENING if alert_url else StrategyState.STOPPED
    if stored.scheduled_broker is not None and stored.spec.schedule.entry_time is not None:
        return StrategyState.SCHEDULED
    return StrategyState.STOPPED


def _pending(strategy_id: str) -> CommandKind | None:
    """Start, stop, kill or close_leg; an alert's own commands are left out."""
    with Session(get_engine()) as session:
        pending = runs_repo.pending_commands_of(session, strategy_id)
    return next((c.kind for c in pending if c.kind is not CommandKind.SIGNAL), None)


def _segments(stored: StoredStrategy) -> tuple[Segment, ...]:
    found: set[Segment] = set()
    if isinstance(stored.spec, OptionsStrategySpec):
        for leg in stored.spec.legs:
            found.add(Segment.FUT if leg.option_type is InstrumentType.FUT else Segment.OPT)
    else:
        for signal_leg in stored.spec.legs:
            instrument = instruments_repo.get_instrument(
                signal_leg.symbol, signal_leg.exchange.value
            )
            kind = instrument.instrument_type if instrument else None
            found.add(
                Segment.FUT
                if kind is InstrumentType.FUT
                else Segment.OPT
                if kind in (InstrumentType.CE, InstrumentType.PE)
                else Segment.EQ
            )
    return tuple(s for s in Segment if s in found)
