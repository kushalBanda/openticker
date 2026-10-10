"""The brain the e2e app opens on: two lessons about the straddle and the
desk, a proposal resting on the first, linked to recent days, and today's
debrief of the straddle's run and an order placed by hand."""

from collections.abc import Callable
from datetime import datetime, timedelta

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, Harness
from openticker.core.brain.lessons import UsePurpose
from openticker.core.brain.notes import Debrief, Hindsight, NoteKind, TradeNote, WrittenBy
from openticker.core.brain.proposals import Proposal
from openticker.events.bus import EventPublisher
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import agent_jobs_repo, brain_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.brain.read import day_trades
from openticker.use_cases.brain.write import raise_proposal, record_lesson_use, write_debrief


def seed_brain(straddle: str, clock: Callable[[], datetime], events: EventPublisher) -> None:
    now = clock()
    days = [
        (now - timedelta(days=back)).astimezone(EXCHANGE_TIMEZONE).date() for back in range(1, 15)
    ]
    weekdays = [d.isoformat() for d in days if d.weekday() < 5][:3]

    def write(
        kind: NoteKind,
        title: str,
        body: str,
        structural: tuple[tuple[NoteKind, str], ...] = (),
    ) -> str:
        with write_transaction() as session:
            note = brain_repo.write_note(
                session,
                None,
                kind,
                "",
                title=title,
                body=body,
                data={},
                state=None,
                strategy_id=None,
                structural=structural,
                written_by=WrittenBy.AGENT_JOB,
                now=now - timedelta(hours=2),
                by="review:" + straddle,
            )
            return note.note_id

    expiry = write(
        NoteKind.LESSON,
        "Exit the straddle by 11:00 on expiry day",
        "Short straddle losses cluster after 11:00 on weekly expiry: gamma grows and one leg "
        f"runs. Seen on [[day:{weekdays[0]}]] and [[day:{weekdays[1]}|the day before]].",
        structural=((NoteKind.STRATEGY, straddle),),
    )
    opening = write(
        NoteKind.LESSON,
        "No entries in the first 5 minutes",
        f"Opening prints were wide on [[day:{weekdays[2]}]]; costs ate the move.",
    )
    raise_proposal(
        Proposal(
            straddle,
            "Straddle: exit by 11:00 on expiry",
            f"On expiry day exit both legs at 11:00. Based on [[lesson:{expiry}]]: the "
            f"losses on [[day:{weekdays[0]}]] came after 11:00.",
            "Two expiry days is a small sample; the best expiry days may pay after 11:00.",
            (expiry,),
        ),
        events,
        now - timedelta(minutes=90),
        "review:" + straddle,
    )
    record_lesson_use(
        expiry,
        UsePurpose.REVIEW,
        straddle,
        "Kept the 11:00 exit on expiry days in the verdict",
        None,
        now - timedelta(hours=1),
        "review:" + straddle,
    )

    # The desk's strategies were designed with it in mind (the Learning line).
    record_lesson_use(
        opening,
        UsePurpose.DESIGN,
        None,
        "Entries at 09:20, not at the open",
        None,
        now - timedelta(minutes=5),
        "mcp:claude-code",
    )

    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    trades, _ = day_trades(today)
    run = next(t for t in trades if t.strategy_id == straddle)
    by_hand = next(t for t in trades if t.order_id and t.triggered_by == "mcp:claude-code")
    write_debrief(
        Debrief(
            today,
            "Straddle sold into rich IV; one hand trade on HDFCBANK",
            f"NIFTY opened flat. [[strategy:{straddle}]] sold both legs at entry and held. "
            f"See [[lesson:{expiry}]].",
            (
                TradeNote(
                    run.run_id,
                    None,
                    "Scheduled entry; IV above its 20-day mean",
                    "Gamma risk into the afternoon for the decay",
                ),
                TradeNote(
                    None,
                    by_hand.order_id,
                    "Faded the gap at the open",
                    "No stop: sized small instead",
                ),
            ),
            (
                Hindsight("Waiting 15 minutes would have sold higher premium", False),
                Hindsight("The HDFCBANK gap was under 0.4%: too small to pay its costs", True),
            ),
        ),
        events,
        now,
        load_calendar(),
        "debrief:" + today.isoformat(),
    )
    with write_transaction() as session:
        job = agent_jobs_repo.add_job(
            session,
            AgentJobKind.DEBRIEF,
            None,
            Harness.CLAUDE,
            "ui",
            now - timedelta(minutes=30),
            subject=today,
        )
        agent_jobs_repo.mark_running(session, job.id, 4343, now - timedelta(minutes=30))
        agent_jobs_repo.end_job(
            session,
            job.id,
            AgentJobEndReason.FINISHED,
            "exited with code 0",
            now - timedelta(minutes=26),
            exit_code=0,
            summary="Straddle sold into rich IV; one hand trade on HDFCBANK. 2 checks answered.",
            cost_usd=0.31,
        )
