"""Reading the brain: the graph of its notes, searching them, one note with
its links, and a trading day's record. A lesson's status is derived here
from its checks on every read; strategy and symbol notes are kept in step
with the strategies.

A day's numbers are never stored in its note: the record is read from the
trade book, the runs and the daily P&L each time, and the debrief's words
are joined to it by run or order id. The one exception is a paper account
reset, which deletes that record: a debriefed day's record is frozen into
its note first, and read from there after."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Literal

from openticker.core.brain.learning import Learning, LessonAt, count_learning, learning
from openticker.core.brain.lessons import (
    NO_CHECKS,
    Held,
    LessonStatus,
    lesson_status,
    next_step,
    parse_evidence,
)
from openticker.core.brain.notes import BrainNoteError, FactKind, NoteKind, Ref, parse_refs
from openticker.core.brain.proposals import request_text
from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayPnl, day_figures, day_pnl
from openticker.core.strategies.models import OptionsStrategySpec
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Product, Side
from openticker.storage.sqlite import brain_repo, pnl_repo, runs_repo, sandbox_repo
from openticker.storage.sqlite.brain_repo import (
    DeskStrategy,
    LessonCheck,
    LessonUse,
    Link,
    Note,
    NoteHead,
    OwedCheck,
)
from openticker.storage.sqlite.sandbox_repo import StoredTrade
from openticker.storage.sqlite.strategies_repo import list_strategies
from openticker.use_cases.pnl_history import day_window, figures_on, trading_day

Window = Literal["7", "30", "90", "all"]
GRAPH_LIMIT = 1000
MAX_SEARCH = 100
MAX_DAY_FILLS = 1000
MAX_LESSON_CHECKS = 200  # on a lesson's page, latest first
MAX_LESSON_USES = 50
MAX_OWED = 100
MAX_LEARNING_DAYS = 365


class UnknownNoteError(LookupError):
    pass


@dataclass(frozen=True)
class Found:
    """A note as a list shows it."""

    head: NoteHead
    status: str | None  # a lesson's derived status, or a proposal's state
    held: Held | None  # a lesson's checks
    applies_to: frozenset[str] | None  # a lesson's strategy ids; empty: desk-wide
    reason: str | None  # a rejected proposal's


@dataclass(frozen=True)
class GraphView:
    notes: list[NoteHead]
    status: Mapping[str, str]  # by note id: lessons' derived status, proposals' state
    links: list[Link]
    day_net: Mapping[str, float | None]  # by day note id: net after charges, when recorded
    truncated: bool


@dataclass(frozen=True)
class LessonFacts:
    """What a lesson's page shows besides its text."""

    checks: list[LessonCheck]  # latest run or order first, at most MAX_LESSON_CHECKS
    uses: list[LessonUse]  # newest first, at most MAX_LESSON_USES
    used: int  # uses in all
    owed: list[OwedCheck]  # runs and orders it applies to that haven't been checked
    evidence: list[Ref]  # the days, runs and orders it came from


@dataclass(frozen=True)
class ProposalFacts:
    """What a proposal's page shows besides its text."""

    change: str
    wrong_if: str
    strategy_name: str | None  # None once the strategy is deleted
    based_on: list[Found]  # the lessons it rests on, with their status now
    request: str  # what to paste into an agent once it's accepted
    earlier: list[Found]  # the strategy's other proposals, newest first


@dataclass(frozen=True)
class NoteView:
    note: Note
    status: str | None
    held: Held | None
    next_step: str | None  # a lesson's
    applies_to: frozenset[str] | None
    links_out: list[Found]
    backlinks: list[Found]
    facts: list[Ref]  # [[run:…]] and [[order:…]] in its text
    lesson: LessonFacts | None = None
    proposal: ProposalFacts | None = None
    local_links: list[Link] = field(default_factory=list)  # among it and its neighbours, once each


@dataclass(frozen=True)
class DayTrade:
    """A run's fills that day, or one order placed outside a strategy, with
    the debrief's words on it when they were written."""

    run_id: str | None
    order_id: str | None  # exactly one of the two
    strategy_id: str | None
    strategy_name: str | None  # None once the strategy is deleted
    triggered_by: str  # who placed it (ADR 35)
    fills: tuple[StoredTrade, ...]  # oldest first
    run_status: str | None  # a run's: open, stopping, ended
    stop_reason: str | None  # why an ended run stopped
    ended_at: datetime | None  # a run's end, or the order's last fill
    why: str | None
    trade_off: str | None

    @property
    def subject(self) -> str:
        return f"run:{self.run_id}" if self.run_id else f"order:{self.order_id}"

    @property
    def realized_pnl(self) -> float | None:
        """What the day's fills closed, before charges; None when one didn't record it."""
        if any(f.realized_pnl is None for f in self.fills):
            return None
        return round(sum(f.realized_pnl or 0.0 for f in self.fills), 2)

    @property
    def charges(self) -> float:
        return round(sum(f.charges or 0.0 for f in self.fills), 2)

    @property
    def net(self) -> float | None:
        realized = self.realized_pnl
        return None if realized is None else round(realized - self.charges, 2)


@dataclass(frozen=True)
class DayRecord:
    trading_date: date
    figures: DayPnl  # net is None when an open position had no price
    live: bool  # worked out now, not read from the record after the close
    trades: list[DayTrade]  # runs, then orders outside strategies, each oldest first
    truncated: bool  # more than MAX_DAY_FILLS fills: the rest are left out
    owed: list[OwedCheck]  # lessons not yet checked against the day's runs and orders
    checks: list[tuple[LessonCheck, str]]  # given on the day's runs and orders, with lesson titles
    note: Note | None  # the day's note, with the debrief when one was written
    frozen_at: datetime | None = None  # read from the note: the account was reset then


def sync_desk(now: datetime) -> None:
    """A note for every strategy and each symbol it trades."""
    desk = []
    for stored in list_strategies():
        spec = stored.spec
        if isinstance(spec, OptionsStrategySpec):
            symbols: tuple[str, ...] = (f"{spec.exchange.value}:{spec.underlying}",)
        else:
            symbols = tuple(
                dict.fromkeys(f"{leg.exchange.value}:{leg.symbol}" for leg in spec.legs)
            )
        desk.append(DeskStrategy(stored.id, stored.name, symbols))
    brain_repo.sync_strategies(desk, now)


def get_graph(window: Window, now: datetime, calendar: MarketCalendar) -> GraphView:
    """The notes of the last `window` trading days (strategies and symbols
    always) and the links among them; at most GRAPH_LIMIT, newest first."""
    sync_desk(now)
    since = None if window == "all" else _trading_days_back(int(window), now, calendar)
    notes, links, truncated = brain_repo.graph(since, GRAPH_LIMIT)
    days = {n.key: n.note_id for n in notes if n.kind is NoteKind.DAY}
    day_net: dict[str, float | None] = {}
    if days:
        dates = sorted(date.fromisoformat(d) for d in days)
        recorded = {
            p.trading_date.isoformat(): p.net_pnl
            for p in pnl_repo.days_between(dates[0], dates[-1])
        }
        day_net = {note_id: recorded.get(key) for key, note_id in days.items()}
        missing = [note_id for note_id, net in day_net.items() if net is None]
        if missing:
            with brain_repo.reading() as session:
                for head in brain_repo.heads(session, missing):
                    if (frozen := _frozen_net(head)) is not None:
                        day_net[head.note_id] = frozen
    return GraphView(notes, _statuses(notes), links, day_net, truncated)


def search_brain(
    query: str | None,
    kind: NoteKind | None,
    status: str | None,
    strategy_id: str | None,
    limit: int,
    now: datetime,
) -> list[Found]:
    """Notes by text, kind, status (a lesson's or a proposal's) or strategy,
    newest first."""
    sync_desk(now)
    heads = brain_repo.search(query, kind, strategy_id, None if status else limit)
    found = _found(heads)
    if status:
        found = [f for f in found if f.status == status]
    return found[:limit]


def get_note(note_id: str) -> NoteView:
    note = brain_repo.get_note(note_id)
    if note is None:
        raise UnknownNoteError(f"no note {note_id}; search_brain or get_brain_graph finds them")
    [found] = _found([note])
    out, back = brain_repo.links_of(note_id)
    facts = [
        r
        for r in parse_refs(note.body + "\n" + (note.user_body or ""))
        if isinstance(r.kind, FactKind)
    ]
    return NoteView(
        note=note,
        status=found.status,
        held=found.held,
        next_step=(
            next_step(found.held, LessonStatus(found.status))
            if found.held is not None and found.status
            else None
        ),
        applies_to=found.applies_to,
        links_out=_found(out),
        backlinks=_found(back),
        facts=list(dict.fromkeys(facts)),
        lesson=_lesson_facts(note, found.status) if note.kind is NoteKind.LESSON else None,
        proposal=_proposal_facts(note) if note.kind is NoteKind.PROPOSAL else None,
        local_links=brain_repo.local_links(note_id),
    )


MAX_EARLIER = 10


def _proposal_facts(note: Note) -> ProposalFacts:
    data = note.data
    change = str(data.get("change") or note.title)
    based = data.get("based_on")
    lesson_ids = [str(b) for b in based] if isinstance(based, list) else []
    with brain_repo.reading() as session:
        lessons = brain_repo.heads(session, lesson_ids) if lesson_ids else []
    order = {lesson_id: n for n, lesson_id in enumerate(lesson_ids)}
    strategy_id = note.strategy_id or ""
    names = {s.id: s.name for s in list_strategies()}
    earlier = [
        h
        for h in brain_repo.search(None, NoteKind.PROPOSAL, strategy_id, MAX_EARLIER + 1)
        if h.note_id != note.note_id and h.strategy_id == strategy_id
    ][:MAX_EARLIER]
    return ProposalFacts(
        change=change,
        wrong_if=str(data.get("wrong_if") or ""),
        strategy_name=names.get(strategy_id),
        based_on=sorted(_found(lessons), key=lambda f: order[f.head.note_id]),
        request=request_text(strategy_id, names.get(strategy_id), change, note.note_id),
        earlier=_found(earlier),
    )


def _lesson_facts(note: Note, status: str | None) -> LessonFacts:
    evidence = note.data.get("evidence")
    try:
        refs = (
            list(parse_evidence([str(e) for e in evidence])) if isinstance(evidence, list) else []
        )
    except BrainNoteError:
        refs = []
    with brain_repo.reading() as session:
        checks = brain_repo.checks_of(session, note.note_id, MAX_LESSON_CHECKS)
        uses, used = brain_repo.uses_of(session, note.note_id, MAX_LESSON_USES)
        owed = (
            []
            if status == LessonStatus.RETIRED.value
            else brain_repo.owed_checks(session, None, None, note.note_id, MAX_OWED)
        )
    return LessonFacts(checks, uses, used, owed, refs)


def get_day_record(
    trading_date: date, broker: BrokerPort, now: datetime, calendar: MarketCalendar
) -> DayRecord:
    """One trading day as the record has it: its P&L after charges, its
    trades by run or order with who placed them, the lessons owed a check,
    and the debrief's words joined to the trades they explain."""
    check_trading_day(trading_date, now, calendar)
    note = brain_repo.find_note(NoteKind.DAY, trading_date.isoformat())
    words = _trade_words(note)
    frozen = _frozen(note)
    if frozen is not None:
        figures, trades, frozen_at = frozen
        truncated, live = False, False
    else:
        trades, truncated = day_trades(trading_date)
        figures, live = _figures(trading_date, broker, now, calendar)
        frozen_at = None
    trades = [
        replace(t, why=w[0], trade_off=w[1]) if (w := words.get(t.subject)) else t for t in trades
    ]
    with brain_repo.reading() as session:
        checks = brain_repo.checks_on(session, [t.subject for t in trades]) if trades else []
    return DayRecord(
        trading_date=trading_date,
        figures=figures,
        live=live,
        trades=trades,
        truncated=truncated,
        owed=owed_on(trading_date),
        checks=checks,
        note=note,
        frozen_at=frozen_at,
    )


def subjects_of_day(trading_date: date) -> list[DayTrade]:
    """The day's runs and orders: from its frozen record after a reset,
    else from the trade book."""
    frozen = _frozen(brain_repo.find_note(NoteKind.DAY, trading_date.isoformat()))
    return frozen[1] if frozen is not None else day_trades(trading_date)[0]


def freeze_record(trading_date: date) -> dict[str, Any]:
    """The day's record as a reset will keep it: its recorded figures (or
    its fills', without a net) and its trades."""
    trades, _ = day_trades(trading_date)
    recorded = pnl_repo.days_between(trading_date, trading_date)
    if recorded:
        figures = recorded[0]
    else:
        start, end = day_window(trading_date)
        figures = day_pnl(
            trading_date, day_figures(pnl_repo.fills_between(start, end), [None], 0.0), None
        )
    return {
        "figures": {**asdict(figures), "trading_date": trading_date.isoformat()},
        "trades": [
            {
                "run_id": t.run_id,
                "order_id": t.order_id,
                "strategy_id": t.strategy_id,
                "strategy_name": t.strategy_name,
                "triggered_by": t.triggered_by,
                "run_status": t.run_status,
                "stop_reason": t.stop_reason,
                "ended_at": t.ended_at.isoformat() if t.ended_at else None,
                "fills": [
                    {
                        "order_id": f.order_id,
                        "filled_at": f.filled_at.isoformat(),
                        "exchange": f.exchange,
                        "symbol": f.symbol,
                        "side": f.side.value,
                        "quantity": f.quantity,
                        "price": f.price,
                        "product": f.product.value,
                        "triggered_by": f.triggered_by,
                        "strategy_id": f.strategy_id,
                        "run_id": f.run_id,
                        "charges": f.charges,
                        "realized_pnl": f.realized_pnl,
                    }
                    for f in t.fills
                ],
            }
            for t in trades
        ],
    }


def _frozen(note: Note | None) -> tuple[DayPnl, list[DayTrade], datetime] | None:
    """A day's record as frozen into its note by a reset."""
    frozen = note.data.get("frozen") if note else None
    at = note.data.get("frozen_at") if note else None
    if not isinstance(frozen, dict) or not isinstance(at, str):
        return None
    figures = dict(frozen["figures"])
    figures["trading_date"] = date.fromisoformat(figures["trading_date"])
    trades = [
        DayTrade(
            run_id=t["run_id"],
            order_id=t["order_id"],
            strategy_id=t["strategy_id"],
            strategy_name=t["strategy_name"],
            triggered_by=t["triggered_by"],
            fills=tuple(
                StoredTrade(
                    order_id=f["order_id"],
                    filled_at=datetime.fromisoformat(f["filled_at"]),
                    exchange=f["exchange"],
                    symbol=f["symbol"],
                    side=Side(f["side"]),
                    quantity=f["quantity"],
                    price=f["price"],
                    product=Product(f["product"]),
                    triggered_by=f["triggered_by"],
                    strategy_id=f["strategy_id"],
                    run_id=f["run_id"],
                    charges=f["charges"],
                    realized_pnl=f["realized_pnl"],
                )
                for f in t["fills"]
            ),
            run_status=t["run_status"],
            stop_reason=t["stop_reason"],
            ended_at=datetime.fromisoformat(t["ended_at"]) if t["ended_at"] else None,
            why=None,
            trade_off=None,
        )
        for t in frozen["trades"]
    ]
    return DayPnl(**figures), trades, datetime.fromisoformat(at)


def _frozen_net(head: NoteHead) -> float | None:
    note = brain_repo.get_note(head.note_id)
    frozen = _frozen(note)
    return frozen[0].net_pnl if frozen else None


def check_trading_day(trading_date: date, now: datetime, calendar: MarketCalendar) -> None:
    if trading_date > now.astimezone(EXCHANGE_TIMEZONE).date():
        raise BrainNoteError(f"{trading_date} hasn't happened yet")
    if session_hours(trading_date, Exchange.NSE, calendar) is None:
        raise BrainNoteError(f"{trading_date} wasn't a trading day")


def day_trades(trading_date: date) -> tuple[list[DayTrade], bool]:
    """The day's runs (those with fills that day, and those that ended then)
    and its orders outside strategies, without the debrief's words."""
    start, end = day_window(trading_date)
    fills = sandbox_repo.list_trades_between(start, end, MAX_DAY_FILLS + 1)
    truncated = len(fills) > MAX_DAY_FILLS
    fills = fills[:MAX_DAY_FILLS]
    by_run: dict[str, list[StoredTrade]] = {}
    by_order: dict[str, list[StoredTrade]] = {}
    for fill in fills:
        if fill.run_id:
            by_run.setdefault(fill.run_id, []).append(fill)
        else:
            by_order.setdefault(fill.order_id, []).append(fill)
    names = {s.id: s.name for s in list_strategies()}
    trades = [
        DayTrade(
            run_id=run.id,
            order_id=None,
            strategy_id=run.strategy_id,
            strategy_name=names.get(run.strategy_id),
            triggered_by=(
                by_run[run.id][0].triggered_by
                if run.id in by_run
                else f"strategy:{run.strategy_id}"
            ),
            fills=tuple(by_run.get(run.id, ())),
            run_status=run.status.value,
            stop_reason=run.stop_reason.value if run.stop_reason else None,
            ended_at=run.ended_at,
            why=None,
            trade_off=None,
        )
        for run in runs_repo.runs_of_day(by_run, start, end)
    ]
    trades += [
        DayTrade(
            run_id=None,
            order_id=order_id,
            strategy_id=own[0].strategy_id,
            strategy_name=names.get(own[0].strategy_id or ""),
            triggered_by=own[0].triggered_by,
            fills=tuple(own),
            run_status=None,
            stop_reason=None,
            ended_at=own[-1].filled_at,
            why=None,
            trade_off=None,
        )
        for order_id, own in by_order.items()
    ]
    return trades, truncated


def _trade_words(note: Note | None) -> dict[str, tuple[str, str]]:
    """The debrief's why and trade-off by subject ("run:<id>", "order:<id>")."""
    words: dict[str, tuple[str, str]] = {}
    notes = note.data.get("trade_notes") if note else None
    for item in notes if isinstance(notes, list) else []:
        if not isinstance(item, dict):
            continue
        subject = f"run:{item['run_id']}" if item.get("run_id") else f"order:{item.get('order_id')}"
        words[subject] = (str(item.get("why", "")), str(item.get("trade_off", "")))
    return words


def _figures(
    trading_date: date, broker: BrokerPort, now: datetime, calendar: MarketCalendar
) -> tuple[DayPnl, bool]:
    """The day as recorded after its close; today, until then, worked out
    now from the broker's marks. Without either, its fills alone, with no
    net: an open position's change isn't known."""
    recorded = pnl_repo.days_between(trading_date, trading_date)
    if recorded:
        return recorded[0], False
    live = trading_date == trading_day(now, calendar)
    positions = None
    if live:
        try:
            positions = broker.get_positions()
        except BrokerError:
            positions = None
    if positions is not None:
        figures = figures_on(trading_date, positions)
    else:
        start, end = day_window(trading_date)
        figures = day_figures(pnl_repo.fills_between(start, end), [None], 0.0)
    return day_pnl(trading_date, figures, None), live


@dataclass(frozen=True)
class LearningView:
    since: datetime
    learning: Learning


def get_learning(days: int, now: datetime) -> LearningView:
    """Over the last `days` days: of the strategies designed and the reviews
    finished while a lesson applied, how many recorded relying on one; the
    checks given and still owed; how often lessons held."""
    if not 1 <= days <= MAX_LEARNING_DAYS:
        raise BrainNoteError(f"days is 1 to {MAX_LEARNING_DAYS}")
    since = now - timedelta(days=days)
    with brain_repo.reading() as session:
        record = brain_repo.learning_record(session, since)
        ids = [lesson_id for lesson_id, _ in record.lessons]
        heads = brain_repo.heads(session, ids) if ids else []
        scopes = brain_repo.scope_of(session, ids) if ids else {}
        owed = brain_repo.owed_checks(session, since, now)
    statuses = _statuses(heads)
    live = {i for i, status in statuses.items() if status != LessonStatus.RETIRED.value}
    counts = count_learning(
        [LessonAt(i, at, scopes.get(i, frozenset()), i in live) for i, at in record.lessons],
        record.designs,
        record.reviews,
        record.uses,
        record.checks,
        checks_owed=sum(o.lesson_id in live for o in owed),
        lessons_ruled=sum(status == LessonStatus.RULE.value for status in statuses.values()),
    )
    return LearningView(since, learning(counts))


def owed_on(trading_date: date) -> list[OwedCheck]:
    """Owed checks of lessons that aren't retired."""
    start, end = day_window(trading_date)
    with brain_repo.reading() as session:
        owed = brain_repo.owed_checks(session, start, end)
        lessons = brain_repo.heads(session, {o.lesson_id for o in owed}) if owed else []
    live = {f.head.note_id for f in _found(lessons) if f.status != LessonStatus.RETIRED.value}
    return [o for o in owed if o.lesson_id in live]


def _found(heads: list[NoteHead]) -> list[Found]:
    lesson_ids = [h.note_id for h in heads if h.kind is NoteKind.LESSON]
    with brain_repo.reading() as session:
        held = brain_repo.held_counts(session, lesson_ids) if lesson_ids else {}
        scopes = brain_repo.scope_of(session, lesson_ids) if lesson_ids else {}
    found = []
    for head in heads:
        if head.kind is NoteKind.LESSON:
            counts = held.get(head.note_id, NO_CHECKS)
            status = lesson_status(counts, head.override)
            found.append(Found(head, status.value, counts, scopes.get(head.note_id), None))
        elif head.kind is NoteKind.PROPOSAL:
            found.append(Found(head, head.state, None, None, head.reason))
        else:
            found.append(Found(head, None, None, None, None))
    return found


def _statuses(notes: list[NoteHead]) -> dict[str, str]:
    return {f.head.note_id: f.status for f in _found(notes) if f.status is not None}


def _trading_days_back(count: int, now: datetime, calendar: MarketCalendar) -> date:
    """The earliest of the last `count` trading days, today's included."""
    day = trading_day(now, calendar)
    seen = 1
    while seen < count:
        day -= timedelta(days=1)
        if session_hours(day, Exchange.NSE, calendar) is not None:
            seen += 1
    return day
