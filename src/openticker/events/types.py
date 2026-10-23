"""Domain events: facts that happened, published by use cases and consumed by
subscribers the use cases know nothing about (ADR 10 in docs/adr)."""

from dataclasses import dataclass, field, is_dataclass
from datetime import UTC, date, datetime


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OrderPlaced:
    order_id: str
    symbol: str
    side: str
    quantity: int
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderFilled:
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderFailed:
    symbol: str
    reason: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderModified:
    """A pending order's quantity, price or trigger changed. Audited, not notified."""

    order_id: str
    symbol: str
    change: str  # "price 950.0 -> 960.0, quantity 10 -> 20"
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderCancelled:
    """A pending order withdrawn by the user, or expired at the session's end."""

    order_id: str
    symbol: str
    reason: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class RiskBreached:
    symbol: str
    reason: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class InstrumentSyncCompleted:
    broker: str
    count: int
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrokerSessionExpired:
    """The broker refused the stored session: live prices have stopped until
    the user logs in again."""

    broker: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrokerConnected:
    """A broker session was stored: the user logged in to the broker (ADR 33)."""

    broker: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrokerDisconnected:
    """The stored broker session was deleted by the user (ADR 33)."""

    broker: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PaperAccountReset:
    """Every paper order, trade and position was deleted and the funds put
    back to the starting capital (ADR 37). Counts are what was deleted."""

    capital: float
    orders: int
    trades: int
    positions: int
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentChatStarted:
    """A chat with the user's coding agent began in the web app (ADR 40)."""

    thread_id: str
    title: str
    folder: str
    subject: str | None
    harness: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentChatDeleted:
    """A chat was deleted: gone from the web app, its turns kept as jobs."""

    thread_id: str
    title: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentSettingsChanged:
    """The web app's Settings changed how the user's coding agent runs (ADR 40):
    a folder's default, the harness every folder uses, the background runs a
    day, or all of them back to the environment."""

    change: str  # folder, harness, runs_per_day, reset
    summary: str  # what it is now: "Reviews: opus, high", "Runs a day: 30"
    triggered_by: str
    folder: str | None = None  # a FolderKind, for change "folder"
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class WatchlistChanged:
    """A watchlist was created, renamed or deleted, or instruments were added
    to or removed from it (ADR 36). Audited, so the web app hears of an
    agent's change as it does of any other."""

    watchlist_id: str
    name: str
    change: str  # created, renamed, deleted, added, removed
    triggered_by: str
    symbols: tuple[str, ...] = ()  # added or removed, as OpenTicker names them
    previous_name: str | None = None  # renamed only
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PositionSettled:
    """An expired futures or options position closed at its settlement price."""

    symbol: str
    product: str
    quantity: int  # signed, as held before settlement
    price: float
    realized_pnl: float
    detail: str  # how the price was reached
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyStarted:
    strategy_id: str
    run_id: str
    name: str
    legs: str  # what it entered, e.g. "SELL 75 NIFTY29SEP2623350CE @ 160.05, ..."
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyScheduleChanged:
    """A strategy was scheduled or unscheduled (ADR 46): audited with the
    broker it entered through before, so one taken away can be seen and put
    back. Its entry time stays in its definition either way."""

    strategy_id: str
    name: str
    broker: str | None  # the broker its scheduled entries go through; None: unscheduled
    previous_broker: str | None
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyLegClosed:
    strategy_id: str
    run_id: str
    leg_id: str
    symbol: str
    reason: str
    detail: str
    realized_pnl: float
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyStopped:
    """A run ended: every leg it opened is closed, or could not be."""

    strategy_id: str
    run_id: str
    name: str
    reason: str
    detail: str
    realized_pnl: float
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ScriptStarted:
    script_id: str
    run_id: str
    name: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ScriptScheduleChanged:
    """A hosted script was scheduled or unscheduled (ADR 46): audited with
    the schedule it had, so one taken away can be seen and put back."""

    script_id: str
    name: str
    schedule: str | None  # "09:15-15:10 Mon-Fri NSE"; None: unscheduled
    previous: str | None
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ScriptExited:
    """A hosted script's process ended, whatever the reason (ADR 25)."""

    script_id: str
    run_id: str
    name: str
    reason: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ChargeRatesDiffer:
    """The broker's contract note charged a sample order differently from the
    rates the sandbox charges: the rates file needs updating (ADR 28)."""

    broker: str
    rates_as_of: str  # the rates file's date
    differing: int  # samples that differ
    checked: int  # samples the broker priced
    detail: str  # each differing figure, ours and the broker's
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ChargeRatesChecked:
    """A charge-rate check ran, whatever it found: when the rates were last
    checked against the broker (ADR 28). Audited, not notified."""

    broker: str
    rates_as_of: str  # the rates file's date
    differing: int
    checked: int
    skipped: int  # segments with no sample priced
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentJobStarted:
    """The daemon started the user's coding agent on a job (ADR 29). Audited."""

    job_id: str
    kind: str
    strategy_id: str | None  # a review's; None for a debrief
    subject: date | None  # the trading date a debrief covers
    title: str  # what people see it called: "Review of …", "Debrief of Mon 5 Oct"
    harness: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentJobEnded:
    """An agent job ended, whatever the reason; a review's summary starts
    with its verdict."""

    job_id: str
    kind: str
    strategy_id: str | None  # a review's; None for a debrief
    subject: date | None  # the trading date a debrief covers
    title: str  # what people see it called
    strategy_name: str | None  # kept for readers of older entries; title is what's shown
    reason: str
    detail: str
    summary: str | None
    cost_usd: float | None
    model_used: str | None = None  # as the harness reported it (ADR 40)
    thread_id: str | None = None  # a chat turn's chat; its title is the chat's
    trigger: str | None = None  # who asked for the job: a desk manager's wake is "manager-wake:…"
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DebriefWritten:
    """A trading day's debrief was written, or written again: the agent's
    part of the day's note in the brain."""

    trading_date: date
    note_id: str
    headline: str
    triggered_by: str
    quiet: bool = False  # the server's one line on a day with nothing to debrief
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrainNoteEdited:
    """The user's own part of a note changed. The text it replaced is kept
    here, so an edit made over someone else's is never lost."""

    note_id: str
    kind: str
    title: str
    previous: str | None
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LessonWritten:
    """A lesson was created, or its text or scope changed."""

    lesson_id: str
    title: str
    change: str  # created, edited
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LessonStatusChanged:
    """A lesson's status moved: a check changed its counts, or a person
    retired, reinstated or cleared it (`reason`)."""

    lesson_id: str
    title: str
    previous: str
    status: str
    held: int
    checks: int
    triggered_by: str
    override: str | None = None  # the person's override after the change
    reason: str | None = None
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ProposalRaised:
    """An agent proposed one change to a strategy, for the user to decide."""

    proposal_id: str
    strategy_id: str
    change: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ProposalDecided:
    """The user accepted, rejected (with a reason) or put off a proposal."""

    proposal_id: str
    strategy_id: str
    change: str
    decision: str  # accept, reject, later
    reason: str | None
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ManagerNumbersChanged:
    """A line of the desk manager's changed (ADR 41): its capital and stop for
    the desk, its own trades, a strategy or a script. `kept_yours`: the
    manager wanted these numbers on a line the user set, which stands."""

    key: str
    name: str | None
    capital: float | None
    stop: float | None
    set_by: str  # manager or you
    kept_yours: bool
    reason: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ManagerWoke:
    """The desk manager woke: a turn of its day's thread is queued (ADR 41)."""

    reason: str  # plan, asked, broke, line, scheduled, fallback, close
    detail: str
    thread_id: str
    job_id: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PlannedCall:
    """One strategy's, script's or its own trades' call in a plan: runs,
    holds or sits_out, and why."""

    key: str
    name: str | None
    call: str
    why: str


@dataclass(frozen=True)
class ManagerPlanSet:
    """The desk manager set the day's plan: its headline, each one's call,
    what it watches, and the lessons it relied on."""

    trading_date: date
    text: str
    lesson_ids: tuple[str, ...]
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)
    items: tuple[PlannedCall, ...] = ()
    watch: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagerSwitched:
    """The user turned the desk manager on or off, or changed its wakes a day."""

    enabled: bool
    wakes_per_day: int
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ManagerStalled:
    """The desk manager can't go on today on its own: its last turns failed,
    or today's wakes are used up. Told once each; the user must act."""

    why: str  # "failing" or "capped"
    detail: str
    thread_id: str | None
    occurred_at: datetime = field(default_factory=_now)


# Every event's name, as the audit log records it.
EVENT_TYPE_NAMES = tuple(
    name
    for name, value in list(globals().items())
    if isinstance(value, type) and is_dataclass(value)
)
