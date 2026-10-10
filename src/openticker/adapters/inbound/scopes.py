"""What each API key may reach, for REST and for MCP over HTTP alike (ADR 17,
ADR 25 and ADR 29 in docs/adr).

Every MCP tool has a REST route (ADR 17), so one table of routes decides
both: an MCP call is allowed exactly when its tool's route would be.

- A full key reaches everything.
- A hosted script's key (`script:<id>`) reaches prices, orders and
  positions (ADR 25).
- A review job's key (`review:<strategy_id>`) reads that one strategy (its
  definition, ledger, runs and signals), market data and the brain's notes.
  Its only writes are appends to the brain about its own strategy: a check
  of a lesson on one of its runs, a lesson's use, a proposal. It can't
  place an order, change or start a strategy, or see another strategy's
  runs.
- A debrief job's key (`debrief:<date>`) reads the desk (strategies, their
  runs and ledgers, trades, P&L, the audit log, market data) and the brain,
  and writes the brain: its own day's debrief, lessons and their checks,
  uses and proposals. It can't place an order, change a strategy, decide a
  proposal, retire a lesson or touch another day's debrief.
"""

from collections.abc import Callable, Mapping

from openticker.use_cases.api_keys import (
    DEBRIEF_SCOPE_PREFIX,
    FULL_SCOPE,
    REVIEW_SCOPE_PREFIX,
    SCRIPT_SCOPE_PREFIX,
)

# Every MCP tool's REST route (ADR 17).
TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "get_broker_login_url": ("GET", "/api/v1/brokers/{broker}/login-url"),
    "connect_broker": ("POST", "/api/v1/brokers/connect"),
    "sync_instruments": ("POST", "/api/v1/instruments/sync"),
    "search_instruments": ("GET", "/api/v1/instruments"),
    "get_quote": ("GET", "/api/v1/quote"),
    "get_quotes": ("POST", "/api/v1/quotes"),
    "get_market_depth": ("GET", "/api/v1/depth"),
    "get_historical_bars": ("GET", "/api/v1/bars"),
    "get_option_chain": ("GET", "/api/v1/option-chain"),
    "preview_payoff": ("POST", "/api/v1/options/payoff"),
    "place_order": ("POST", "/api/v1/orders"),
    "place_basket": ("POST", "/api/v1/orders/basket"),
    "get_margin": ("POST", "/api/v1/margin"),
    "preview_paper_margin": ("GET", "/api/v1/margin/paper"),
    "preview_charges": ("GET", "/api/v1/charges/preview"),
    "check_charge_rates": ("POST", "/api/v1/charges/check"),
    "get_orderbook": ("GET", "/api/v1/orders"),
    "get_positions": ("GET", "/api/v1/positions"),
    "get_funds": ("GET", "/api/v1/funds"),
    "evaluate_risk": ("POST", "/api/v1/risk/evaluate"),
    "get_audit_log": ("GET", "/api/v1/audit"),
    "get_market_status": ("GET", "/api/v1/market-status"),
    "cancel_order": ("DELETE", "/api/v1/orders/{order_id}"),
    "cancel_all_orders": ("POST", "/api/v1/orders/cancel-all"),
    "close_position": ("POST", "/api/v1/positions/close"),
    "close_all_positions": ("POST", "/api/v1/positions/close-all"),
    "modify_order": ("PATCH", "/api/v1/orders/{order_id}"),
    "get_order_status": ("GET", "/api/v1/orders/{order_id}"),
    "get_tradebook": ("GET", "/api/v1/trades"),
    "get_pnl_history": ("GET", "/api/v1/pnl/history"),
    "get_charges_summary": ("GET", "/api/v1/charges/summary"),
    "list_watchlists": ("GET", "/api/v1/watchlists"),
    "create_watchlist": ("POST", "/api/v1/watchlists"),
    "rename_watchlist": ("PATCH", "/api/v1/watchlists/{watchlist_id}"),
    "delete_watchlist": ("DELETE", "/api/v1/watchlists/{watchlist_id}"),
    "add_to_watchlist": ("POST", "/api/v1/watchlists/{watchlist_id}/instruments"),
    "remove_from_watchlist": ("DELETE", "/api/v1/watchlists/{watchlist_id}/instruments"),
    "create_strategy": ("POST", "/api/v1/strategies"),
    "list_strategies": ("GET", "/api/v1/strategies"),
    "get_strategy": ("GET", "/api/v1/strategies/{strategy_id}"),
    "update_strategy": ("PUT", "/api/v1/strategies/{strategy_id}"),
    "delete_strategy": ("DELETE", "/api/v1/strategies/{strategy_id}"),
    "preview_strategy": ("GET", "/api/v1/strategies/{strategy_id}/preview"),
    "start_strategy": ("POST", "/api/v1/strategies/{strategy_id}/start"),
    "stop_strategy": ("POST", "/api/v1/strategies/{strategy_id}/stop"),
    "kill_strategy": ("POST", "/api/v1/strategies/{strategy_id}/kill"),
    "release_kill_switch": ("POST", "/api/v1/strategies/{strategy_id}/release"),
    "schedule_strategy": ("POST", "/api/v1/strategies/{strategy_id}/schedule"),
    "unschedule_strategy": ("DELETE", "/api/v1/strategies/{strategy_id}/schedule"),
    "close_strategy_leg": ("POST", "/api/v1/strategies/{strategy_id}/legs/{leg_id}/close"),
    "get_strategy_runs": ("GET", "/api/v1/strategies/{strategy_id}/runs"),
    "get_strategy_ledger": ("GET", "/api/v1/strategies/{strategy_id}/ledger"),
    "get_strategy_run": ("GET", "/api/v1/runs/{run_id}"),
    "start_review": ("POST", "/api/v1/strategies/{strategy_id}/review"),
    "schedule_review": ("POST", "/api/v1/strategies/{strategy_id}/review-schedule"),
    "unschedule_review": ("DELETE", "/api/v1/strategies/{strategy_id}/review-schedule"),
    "get_agent_jobs": ("GET", "/api/v1/agent-jobs"),
    "get_agent_job_log": ("GET", "/api/v1/agent-jobs/{job_id}/log"),
    "stop_agent_job": ("POST", "/api/v1/agent-jobs/{job_id}/stop"),
    "create_signal_strategy": ("POST", "/api/v1/signal-strategies"),
    "update_signal_strategy": ("PUT", "/api/v1/signal-strategies/{strategy_id}"),
    "rotate_strategy_webhook": ("POST", "/api/v1/strategies/{strategy_id}/webhook"),
    "disable_strategy_webhook": ("DELETE", "/api/v1/strategies/{strategy_id}/webhook"),
    "get_strategy_signals": ("GET", "/api/v1/strategies/{strategy_id}/signals"),
    "upload_script": ("POST", "/api/v1/scripts"),
    "list_scripts": ("GET", "/api/v1/scripts"),
    "get_script": ("GET", "/api/v1/scripts/{script_id}"),
    "update_script": ("PUT", "/api/v1/scripts/{script_id}"),
    "delete_script": ("DELETE", "/api/v1/scripts/{script_id}"),
    "start_script": ("POST", "/api/v1/scripts/{script_id}/start"),
    "stop_script": ("POST", "/api/v1/scripts/{script_id}/stop"),
    "schedule_script": ("POST", "/api/v1/scripts/{script_id}/schedule"),
    "unschedule_script": ("DELETE", "/api/v1/scripts/{script_id}/schedule"),
    "get_script_logs": ("GET", "/api/v1/scripts/{script_id}/logs"),
    "get_brain_graph": ("GET", "/api/v1/brain/graph"),
    "search_brain": ("GET", "/api/v1/brain/notes"),
    "get_brain_note": ("GET", "/api/v1/brain/notes/{note_id}"),
    "get_day_record": ("GET", "/api/v1/brain/days/{trading_date}/record"),
    "write_debrief": ("PUT", "/api/v1/brain/days/{trading_date}"),
    "create_lesson": ("POST", "/api/v1/brain/lessons"),
    "update_lesson": ("PATCH", "/api/v1/brain/lessons/{lesson_id}"),
    "check_lesson": ("POST", "/api/v1/brain/lessons/{lesson_id}/checks"),
    "record_lesson_use": ("POST", "/api/v1/brain/lessons/{lesson_id}/uses"),
    "set_lesson_override": ("POST", "/api/v1/brain/lessons/{lesson_id}/override"),
    "raise_proposal": ("POST", "/api/v1/brain/proposals"),
    "decide_proposal": ("POST", "/api/v1/brain/proposals/{proposal_id}/decision"),
    "start_debrief": ("POST", "/api/v1/brain/debrief"),
    "schedule_debrief": ("PUT", "/api/v1/brain/debrief-schedule"),
    "get_debrief_schedule": ("GET", "/api/v1/brain/debrief-schedule"),
    "get_learning": ("GET", "/api/v1/brain/learning"),
}

# Routes with no MCP tool: the user's own text on a note is theirs to edit,
# with a full key or from the web app, never by an agent.
REST_ONLY_ROUTES = frozenset({("PATCH", "/api/v1/brain/notes/{note_id}")})

# A hosted script's key: prices, market depth and margin, placing, reading,
# changing and cancelling orders, and closing one position. Never broker
# login, strategies, scripts, or cancelling or closing everything at once.
SCRIPT_ROUTES = frozenset(
    {
        ("GET", "/api/v1/instruments"),
        ("GET", "/api/v1/quote"),
        ("POST", "/api/v1/quotes"),
        ("GET", "/api/v1/depth"),
        ("GET", "/api/v1/bars"),
        ("GET", "/api/v1/option-chain"),
        ("POST", "/api/v1/options/payoff"),
        ("GET", "/api/v1/market-status"),
        ("POST", "/api/v1/risk/evaluate"),
        ("POST", "/api/v1/margin"),
        ("GET", "/api/v1/margin/paper"),
        ("POST", "/api/v1/orders"),
        ("POST", "/api/v1/orders/basket"),
        ("GET", "/api/v1/orders"),
        ("DELETE", "/api/v1/orders/{order_id}"),
        ("PATCH", "/api/v1/orders/{order_id}"),
        ("GET", "/api/v1/orders/{order_id}"),
        ("GET", "/api/v1/trades"),
        ("GET", "/api/v1/positions"),
        ("POST", "/api/v1/positions/close"),
        ("GET", "/api/v1/funds"),
    }
)

# A review's appends to the brain, each about its own strategy only. Over
# REST their arguments are in the body, which the route checks itself
# (`refusal` with the body's fields); the key's check sees only the path.
REVIEW_BRAIN_WRITES = frozenset(
    {
        ("POST", "/api/v1/brain/lessons/{lesson_id}/checks"),
        ("POST", "/api/v1/brain/lessons/{lesson_id}/uses"),
        ("POST", "/api/v1/brain/proposals"),
    }
)

# A review job's key: its own strategy, read only, market data, the brain's
# notes, and its appends to the brain.
REVIEW_ROUTES = REVIEW_BRAIN_WRITES | frozenset(
    {
        ("GET", "/api/v1/brain/notes"),
        ("GET", "/api/v1/brain/notes/{note_id}"),
        ("GET", "/api/v1/strategies/{strategy_id}"),
        ("GET", "/api/v1/strategies/{strategy_id}/ledger"),
        ("GET", "/api/v1/strategies/{strategy_id}/runs"),
        ("GET", "/api/v1/strategies/{strategy_id}/signals"),
        ("GET", "/api/v1/strategies/{strategy_id}/preview"),
        ("GET", "/api/v1/runs/{run_id}"),
        ("GET", "/api/v1/instruments"),
        ("GET", "/api/v1/quote"),
        ("POST", "/api/v1/quotes"),
        ("GET", "/api/v1/option-chain"),
        ("POST", "/api/v1/options/payoff"),
        ("GET", "/api/v1/market-status"),
        ("GET", "/api/v1/charges/preview"),
    }
)


_BRAIN_READS = (
    "get_brain_graph",
    "search_brain",
    "get_brain_note",
    "get_day_record",
    "get_learning",
)

# A debrief job's key: the desk's reads, the brain's reads and its writes.
DEBRIEF_ROUTES = frozenset(
    TOOL_ROUTES[tool]
    for tool in (
        *_BRAIN_READS,
        "write_debrief",
        "create_lesson",
        "update_lesson",
        "check_lesson",
        "record_lesson_use",
        "raise_proposal",
        "list_strategies",
        "get_strategy",
        "get_strategy_ledger",
        "get_strategy_runs",
        "get_strategy_run",
        "get_strategy_signals",
        "get_tradebook",
        "get_orderbook",
        "get_order_status",
        "get_pnl_history",
        "get_charges_summary",
        "get_audit_log",
        "get_market_status",
        "search_instruments",
        "get_quote",
        "get_quotes",
        "get_option_chain",
    )
)
# The routes whose trading date a debrief's key must keep to its own.
_ITS_DAY = frozenset(TOOL_ROUTES[t] for t in ("get_day_record", "write_debrief"))


def refusal(
    scope: str,
    method: str,
    path: str | None,
    params: Mapping[str, object],
    strategy_of_run: Callable[[str], str | None],
    *,
    whole_call: bool = True,
) -> str | None:
    """Why a key with `scope` may not make this call, or None when it may.
    `params` are the call's path parameters (REST) or arguments (MCP);
    `strategy_of_run` finds which strategy a run belongs to. `whole_call` is
    False when only part of the call is known: a tool being listed, or a
    REST request whose body is checked later by its route."""
    if scope == FULL_SCOPE:
        return None
    route = (method, path)
    if scope.startswith(SCRIPT_SCOPE_PREFIX):
        if route in SCRIPT_ROUTES:
            return None
        return "a script's key reaches prices, orders and positions only"
    if scope.startswith(REVIEW_SCOPE_PREFIX):
        strategy_id = scope.removeprefix(REVIEW_SCOPE_PREFIX)
        if route not in REVIEW_ROUTES:
            return "a review's key reads its own strategy and market data only"
        asked = params.get("strategy_id")
        if asked is not None and asked != strategy_id:
            return f"a review's key reads strategy {strategy_id} only"
        run_id = params.get("run_id")
        if isinstance(run_id, str) and strategy_of_run(run_id) != strategy_id:
            return f"a review's key reads the runs of strategy {strategy_id} only"
        if route in REVIEW_BRAIN_WRITES and whole_call:
            if params.get("order_id") is not None:
                return f"a review's key checks lessons on the runs of strategy {strategy_id} only"
            if route != TOOL_ROUTES["check_lesson"] and asked is None:
                return f"a review's key writes about strategy {strategy_id} only: give strategy_id"
        return None
    if scope.startswith(DEBRIEF_SCOPE_PREFIX):
        day = scope.removeprefix(DEBRIEF_SCOPE_PREFIX)
        if route not in DEBRIEF_ROUTES:
            return "a debrief's key reads the desk and writes the brain only"
        asked = params.get("trading_date")
        if route in _ITS_DAY and asked is not None and str(asked)[:10] != day:
            return f"a debrief's key reads and writes the day {day} only"
        return None
    return f"unknown key scope {scope!r}"
