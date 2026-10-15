from openticker.core.agents.threads import (
    BRAIN_LINE,
    BRAIN_READ_LINE,
    MAX_TITLE_CHARS,
    READ_ONLY_LINE,
    Access,
    Folder,
    chat_prompt_context,
    chat_title,
    folder_context,
    snippet,
)


def test_chat_title_is_the_first_message_on_one_line_cut() -> None:
    assert chat_title("Why did\n  expiry days lose?") == "Why did expiry days lose?"
    long = chat_title("word " * 40)
    assert len(long) == MAX_TITLE_CHARS and long.endswith("…")


def test_folder_context_names_the_strategy_or_script() -> None:
    assert folder_context(Folder.STRATEGY, "stg_1", "NIFTY short straddle") == (
        "This chat is about the OpenTicker strategy 'NIFTY short straddle' (stg_1)."
    )
    assert folder_context(Folder.SCRIPT, "scr_1", None) == (
        "This chat is about the OpenTicker hosted script (since deleted) (scr_1)."
    )
    assert folder_context(Folder.DEBRIEF, "2026-10-12", None) == (
        "This chat is about the OpenTicker trading day 2026-10-12."
    )


def test_general_has_no_folder_context() -> None:
    assert folder_context(Folder.GENERAL, None, None) is None


def test_every_chat_turn_carries_its_job_id() -> None:
    text = chat_prompt_context(None, "job_ab12")

    assert text.endswith("(OpenTicker agent job job_ab12)")
    assert "web app" in text
    assert "strategy 'X'" in chat_prompt_context(folder_context(Folder.STRATEGY, "s", "X"), "j")


def test_a_read_only_chat_tells_its_agent_so() -> None:
    assert READ_ONLY_LINE in chat_prompt_context(None, "j", Access.READ)
    assert "read-only" not in chat_prompt_context(None, "j")


def test_a_snippet_is_the_line_around_the_first_match_cut_with_ellipses() -> None:
    text = "Losses " + "cluster " * 30 + "when INDIA VIX opened high,\n  and " + "more " * 30

    found = snippet(text, "vix", width=40)

    assert found.startswith("…") and found.endswith("…")
    assert "VIX" in found and "\n" not in found
    assert len(found) <= 42
    assert snippet("short answer", "zzz") == "short answer"
    assert snippet("a " * 100, "zzz", width=10) == "a a a a a…"


def test_every_chat_prompt_has_the_brain_line() -> None:
    for folder, subject in ((Folder.GENERAL, None), (Folder.MANAGER, "2026-09-22")):
        assert BRAIN_LINE in chat_prompt_context(folder_context(folder, subject, None), "j")
    read = chat_prompt_context(None, "j", Access.READ)
    assert BRAIN_READ_LINE in read and "record_lesson_use" not in read
