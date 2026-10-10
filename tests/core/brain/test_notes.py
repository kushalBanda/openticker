from datetime import date

import pytest

from openticker.core.brain.notes import (
    BrainNoteError,
    Debrief,
    FactKind,
    Hindsight,
    NoteKind,
    Ref,
    TradeNote,
    WrittenBy,
    day_title,
    note_key,
    parse_refs,
    validate_debrief,
    written_by_of,
)


def test_parse_refs_reads_every_kind_and_label() -> None:
    text = (
        "Per [[lesson:les_1a2b3c|the expiry lesson]], on [[day:2026-10-05]] "
        "[[symbol:nse:reliance]] fell; see [[run:run_9]] and [[order:ord_4|this order]], "
        "and [[strategy:str_7f3a]] and [[proposal:prp_000001]]."
    )
    assert parse_refs(text) == [
        Ref(NoteKind.LESSON, "les_1a2b3c", "the expiry lesson"),
        Ref(NoteKind.DAY, "2026-10-05", None),
        Ref(NoteKind.SYMBOL, "NSE:RELIANCE", None),
        Ref(FactKind.RUN, "run_9", None),
        Ref(FactKind.ORDER, "ord_4", "this order"),
        Ref(NoteKind.STRATEGY, "str_7f3a", None),
        Ref(NoteKind.PROPOSAL, "prp_000001", None),
    ]


def test_unknown_kind_is_text_not_error() -> None:
    assert parse_refs("[[note:x]] [[day:yesterday]] [[symbol:XYZ:A]] [[lesson:]]") == []


def test_note_key_normalises_symbol_and_rejects_bad_date() -> None:
    assert note_key(NoteKind.SYMBOL, " nse:nifty 50 ") == "NSE:NIFTY 50"
    assert note_key(NoteKind.DAY, "2026-10-05") == "2026-10-05"
    with pytest.raises(BrainNoteError, match="YYYY-MM-DD"):
        note_key(NoteKind.DAY, "5 Oct")
    with pytest.raises(BrainNoteError, match="EXCHANGE:SYMBOL"):
        note_key(NoteKind.SYMBOL, "RELIANCE")


def test_day_title() -> None:
    assert day_title(date(2026, 10, 5)) == "Mon 5 Oct"


def debrief(*notes: TradeNote, hindsight: tuple[Hindsight, ...] = ()) -> Debrief:
    return Debrief(date(2026, 10, 5), " A day ", "What happened", notes, hindsight)


def test_debrief_trade_note_needs_exactly_one_of_run_or_order() -> None:
    for neither_or_both in (TradeNote(None, None, "w", "t"), TradeNote("run_1", "SB1", "w", "t")):
        with pytest.raises(BrainNoteError, match="exactly one"):
            validate_debrief(debrief(neither_or_both))
    valid = validate_debrief(debrief(TradeNote(" run_1 ", "", " why ", "")))
    assert valid.headline == "A day"
    assert valid.trade_notes == (TradeNote("run_1", None, "why", ""),)


def test_debrief_limits_and_duplicate_subjects_are_refused() -> None:
    with pytest.raises(BrainNoteError, match="two trade notes about run:run_1"):
        validate_debrief(
            debrief(TradeNote("run_1", None, "a", ""), TradeNote("run_1", None, "b", ""))
        )
    with pytest.raises(BrainNoteError, match="needs a why"):
        validate_debrief(debrief(TradeNote("run_1", None, " ", "")))
    with pytest.raises(BrainNoteError, match="headline"):
        validate_debrief(Debrief(date(2026, 10, 5), " ", "", (), ()))
    with pytest.raises(BrainNoteError, match="at most 200 trade notes"):
        validate_debrief(debrief(*(TradeNote(f"run_{n}", None, "w", "") for n in range(201))))
    with pytest.raises(BrainNoteError, match="at most 20 hindsight"):
        validate_debrief(debrief(hindsight=tuple(Hindsight("x", True) for _ in range(21))))
    with pytest.raises(BrainNoteError, match="2,000"):
        validate_debrief(debrief(TradeNote("run_1", None, "w" * 2001, "")))


def test_written_by_unattended_jobs_or_a_person() -> None:
    assert written_by_of("debrief:2026-10-05") is WrittenBy.AGENT_JOB
    assert written_by_of("review:stg_1") is WrittenBy.AGENT_JOB
    assert written_by_of("mcp:claude-code") is WrittenBy.PERSON
    assert written_by_of("ui") is WrittenBy.PERSON
