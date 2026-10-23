import asyncio

from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.scopes import (
    CHAT_READ_EXTRA_TOOLS,
    CHAT_READ_TOOLS,
    CHAT_ROUTES,
    DEBRIEF_ROUTES,
    REVIEW_ROUTES,
    SCRIPT_ROUTES,
    TOOL_ROUTES,
    refusal,
)

RUNS = {"run_mine": "stg_mine", "run_theirs": "stg_theirs"}


def _refusal(scope: str, tool: str, **params: object) -> str | None:
    method, path = TOOL_ROUTES[tool]
    return refusal(scope, method, path, params, RUNS.get)


def test_a_full_key_reaches_everything() -> None:
    assert all(_refusal("full", tool) is None for tool in TOOL_ROUTES)


def test_a_scripts_key_trades_but_never_manages() -> None:
    assert _refusal("script:scr_1", "place_order") is None
    assert _refusal("script:scr_1", "start_strategy", strategy_id="stg_mine") is not None
    assert _refusal("script:scr_1", "close_all_positions") is not None


def test_a_reviews_key_reads_its_own_strategy_and_market_data() -> None:
    scope = "review:stg_mine"

    assert _refusal(scope, "get_strategy_ledger", strategy_id="stg_mine") is None
    assert _refusal(scope, "get_strategy_run", run_id="run_mine") is None
    assert _refusal(scope, "get_quote") is None
    assert "stg_mine only" in (
        _refusal(scope, "get_strategy_ledger", strategy_id="stg_theirs") or ""
    )
    assert "runs of strategy stg_mine" in (
        _refusal(scope, "get_strategy_run", run_id="run_theirs") or ""
    )
    assert _refusal(scope, "get_strategy_run", run_id="run_gone") is not None


def test_a_reviews_key_never_changes_anything() -> None:
    scope = "review:stg_mine"
    changing = [
        "place_order",
        "start_strategy",
        "stop_strategy",
        "update_strategy",
        "schedule_strategy",
        "create_strategy",
        "start_review",
        "list_strategies",
        "get_funds",
    ]

    for tool in changing:
        assert _refusal(scope, tool, strategy_id="stg_mine") is not None, tool


def test_every_scoped_route_is_a_real_tools_route() -> None:
    routes = set(TOOL_ROUTES.values())

    assert SCRIPT_ROUTES <= routes and REVIEW_ROUTES <= routes and DEBRIEF_ROUTES <= routes


def test_an_unknown_scope_reaches_nothing() -> None:
    assert _refusal("admin", "get_quote") is not None


def test_debrief_key_writes_and_reads_only_its_date() -> None:
    scope = "debrief:2026-10-05"

    assert _refusal(scope, "get_day_record", trading_date="2026-10-05") is None
    assert _refusal(scope, "write_debrief", trading_date="2026-10-05") is None
    assert "2026-10-05 only" in (_refusal(scope, "write_debrief", trading_date="2026-10-02") or "")
    assert _refusal(scope, "get_day_record", trading_date="2026-10-02") is not None
    assert _refusal(scope, "write_debrief") is None  # listed as a tool, without arguments
    for tool in ("check_lesson", "create_lesson", "raise_proposal", "get_tradebook", "get_quote"):
        assert _refusal(scope, tool) is None, tool
    assert _refusal(scope, "get_strategy_run", run_id="run_theirs") is None  # the whole desk


def test_debrief_key_cannot_place_orders_change_strategies_or_decide() -> None:
    scope = "debrief:2026-10-05"
    for tool in (
        "place_order",
        "cancel_order",
        "start_strategy",
        "update_strategy",
        "create_strategy",
        "decide_proposal",
        "set_lesson_override",
        "start_debrief",
        "schedule_debrief",
        "start_review",
        "get_historical_bars",  # caches bars: a write
    ):
        assert _refusal(scope, tool) is not None, tool
    assert refusal(scope, "PATCH", "/api/v1/brain/notes/{note_id}", {}, RUNS.get) is not None


def test_review_key_still_refused_other_strategy_runs() -> None:
    scope = "review:stg_mine"
    assert _refusal(scope, "get_strategy_run", run_id="run_theirs") is not None
    assert _refusal(scope, "write_debrief") is not None
    assert _refusal(scope, "check_lesson", run_id="run_theirs") is not None


def test_review_key_reads_brain_notes_but_not_the_desks_days() -> None:
    scope = "review:stg_mine"

    assert _refusal(scope, "search_brain") is None
    assert _refusal(scope, "search_brain", strategy_id="stg_mine") is None
    assert _refusal(scope, "search_brain", strategy_id="stg_theirs") is not None
    assert _refusal(scope, "get_brain_note", note_id="les_1") is None
    for tool in ("get_day_record", "get_brain_graph", "get_learning", "write_debrief"):
        assert _refusal(scope, tool) is not None, tool


def test_review_key_checks_lesson_only_with_own_run_never_order() -> None:
    scope = "review:stg_mine"

    assert _refusal(scope, "check_lesson", lesson_id="les_1", run_id="run_mine") is None
    assert "runs of strategy stg_mine" in (
        _refusal(scope, "check_lesson", lesson_id="les_1", run_id="run_theirs") or ""
    )
    assert "checks lessons on the runs" in (
        _refusal(scope, "check_lesson", lesson_id="les_1", order_id="ord_1") or ""
    )


def test_review_key_use_and_proposal_require_own_strategy() -> None:
    scope = "review:stg_mine"

    for tool in ("record_lesson_use", "raise_proposal"):
        assert _refusal(scope, tool, lesson_id="les_1", strategy_id="stg_mine") is None, tool
        assert _refusal(scope, tool, lesson_id="les_1", strategy_id="stg_theirs") is not None
        assert "give strategy_id" in (_refusal(scope, tool, lesson_id="les_1") or ""), tool
        assert _refusal(scope, tool, lesson_id="les_1", strategy_id=None) is not None, tool


def test_review_key_lists_its_brain_appends_before_their_arguments_are_known() -> None:
    scope = "review:stg_mine"

    for tool in ("check_lesson", "record_lesson_use", "raise_proposal"):
        method, path = TOOL_ROUTES[tool]
        assert refusal(scope, method, path, {}, RUNS.get, whole_call=False) is None, tool
    for tool in ("decide_proposal", "set_lesson_override", "create_lesson", "update_lesson"):
        assert _refusal(scope, tool) is not None, tool


def test_debrief_key_reads_learning() -> None:
    assert _refusal("debrief:2026-10-05", "get_learning") is None


def test_a_chats_key_trades_runs_strategies_and_writes_the_brain() -> None:
    scope = "chat:thr_1"

    for tool in (
        "place_order",
        "close_all_positions",
        "start_strategy",
        "kill_strategy",
        "get_strategy_ledger",
        "create_lesson",
        "decide_proposal",
        "get_agent_jobs",
    ):
        assert _refusal(scope, tool, strategy_id="stg_theirs") is None, tool


def test_a_chats_key_cannot_sign_in_to_the_broker_or_run_agent_jobs() -> None:
    scope = "chat:thr_1"

    for tool in (
        "get_broker_login_url",
        "connect_broker",
        "start_review",
        "stop_agent_job",
        "start_debrief",
        "schedule_debrief",
    ):
        assert "chat's key" in (_refusal(scope, tool) or ""), tool


def test_the_desk_managers_key_may_start_a_review_only() -> None:
    def manager(tool: str) -> str | None:
        method, path = TOOL_ROUTES[tool]
        return refusal(
            "chat:thr_m", method, path, {}, RUNS.get, is_manager_key=lambda s: s == "chat:thr_m"
        )

    assert manager("start_review") is None
    for tool in ("stop_agent_job", "start_debrief", "set_manager", "wake_manager"):
        assert "chat's key" in (manager(tool) or ""), tool


def test_the_desk_managers_key_holds_things_out_and_never_changes_a_schedule() -> None:
    def call(scope: str, tool: str) -> str | None:
        method, path = TOOL_ROUTES[tool]
        return refusal(
            scope, method, path, {}, RUNS.get, is_manager_key=lambda s: s == "chat:thr_m"
        )

    for tool in (
        "schedule_strategy",
        "unschedule_strategy",
        "schedule_script",
        "unschedule_script",
    ):
        assert "schedules are the user's" in (call("chat:thr_m", tool) or ""), tool
        assert call("chat:thr_1", tool) is None, tool
    for tool in ("set_manager_numbers", "start_strategy", "start_script", "stop_strategy"):
        assert call("chat:thr_m", tool) is None, tool


def test_a_chats_key_reaches_no_route_without_a_tool() -> None:
    scope = "chat:thr_1"

    for method, path in (
        ("POST", "/api/v1/keys"),
        ("POST", "/api/v1/agent-threads"),
        ("POST", "/api/v1/agent-threads/{thread_id}/messages"),
        ("PATCH", "/api/v1/brain/notes/{note_id}"),
    ):
        assert refusal(scope, method, path, {}, RUNS.get) is not None, path


def test_a_read_only_chats_tools_are_exactly_its_chats_read_only_tools() -> None:
    """A read-only chat's key reaches what the MCP annotations call read-only,
    of the tools a chat may use; a tool annotated differently changes it here."""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    read_only = {
        tool.name
        for tool in tools
        if tool.annotations is not None
        and tool.annotations.read_only_hint
        and TOOL_ROUTES[tool.name] in CHAT_ROUTES
    }

    assert set(CHAT_READ_TOOLS) == read_only
    for extra in CHAT_READ_EXTRA_TOOLS:  # writes the local cache only
        assert extra not in read_only and TOOL_ROUTES[extra] in CHAT_ROUTES


def test_a_read_only_chats_key_reads_the_desk_and_changes_nothing() -> None:
    scope = "chat-read:thr_1"

    for tool in ("get_quote", "get_historical_bars", "get_positions", "get_strategy_ledger"):
        assert _refusal(scope, tool, strategy_id="stg_theirs") is None, tool
    for tool in (
        "place_order",
        "cancel_all_orders",
        "start_strategy",
        "create_watchlist",
        "create_lesson",
        "connect_broker",
        "start_review",
    ):
        assert "read-only" in (_refusal(scope, tool) or ""), tool
    assert refusal(scope, "POST", "/api/v1/agent-threads", {}, RUNS.get) is not None


def test_the_managers_days_are_read_by_chats_and_the_manager_not_reviews() -> None:
    for tool in ("get_manager_day", "list_manager_days"):
        assert _refusal("chat:thr_1", tool, trading_date="2026-10-14") is None, tool
        assert _refusal("chat-read:thr_1", tool, trading_date="2026-10-14") is None, tool
        assert _refusal("review:stg_mine", tool, trading_date="2026-10-14") is not None, tool
