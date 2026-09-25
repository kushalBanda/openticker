from openticker.adapters.inbound.scopes import REVIEW_ROUTES, SCRIPT_ROUTES, TOOL_ROUTES, refusal

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

    assert SCRIPT_ROUTES <= routes and REVIEW_ROUTES <= routes


def test_an_unknown_scope_reaches_nothing() -> None:
    assert _refusal("admin", "get_quote") is not None
