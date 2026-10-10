from openticker.adapters.inbound.scopes import (
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
        "schedule_review",
        "unschedule_review",
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
