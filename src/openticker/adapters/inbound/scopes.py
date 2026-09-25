"""What each API key may reach, for REST and for MCP over HTTP alike (ADR 17,
ADR 25 and ADR 29 in docs/adr).

Every MCP tool has a REST route (ADR 17), so one table of routes decides
both: an MCP call is allowed exactly when its tool's route would be.

- A full key reaches everything.
- A hosted script's key (`script:<id>`) reaches prices, orders and
  positions (ADR 25).
- A review job's key (`review:<strategy_id>`) reads that one strategy (its
  definition, ledger, runs and signals) and market data. It can't place an
  order, change or start a strategy, or see another strategy's runs.
"""

from collections.abc import Callable, Mapping

from openticker.use_cases.api_keys import FULL_SCOPE, REVIEW_SCOPE_PREFIX, SCRIPT_SCOPE_PREFIX

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
    "place_order": ("POST", "/api/v1/orders"),
    "place_basket": ("POST", "/api/v1/orders/basket"),
    "get_margin": ("POST", "/api/v1/margin"),
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
}

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
        ("GET", "/api/v1/market-status"),
        ("POST", "/api/v1/risk/evaluate"),
        ("POST", "/api/v1/margin"),
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

# A review job's key: its own strategy, read only, and market data.
REVIEW_ROUTES = frozenset(
    {
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
        ("GET", "/api/v1/market-status"),
        ("GET", "/api/v1/charges/preview"),
    }
)


def refusal(
    scope: str,
    method: str,
    path: str | None,
    params: Mapping[str, object],
    strategy_of_run: Callable[[str], str | None],
) -> str | None:
    """Why a key with `scope` may not make this call, or None when it may.
    `params` are the call's path parameters (REST) or arguments (MCP);
    `strategy_of_run` finds which strategy a run belongs to."""
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
        if "strategy_id" in params and params["strategy_id"] != strategy_id:
            return f"a review's key reads strategy {strategy_id} only"
        run_id = params.get("run_id")
        if isinstance(run_id, str) and strategy_of_run(run_id) != strategy_id:
            return f"a review's key reads the runs of strategy {strategy_id} only"
        return None
    return f"unknown key scope {scope!r}"
