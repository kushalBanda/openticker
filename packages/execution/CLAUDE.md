# CLAUDE.md — packages/execution

This file gives guidance for work inside `packages/execution`. Read the root `/CLAUDE.md` first for workspace-wide rules.

## What this package does

`execution` is the pre-trade risk pipeline and broker implementations for paper trading. Its paper broker was promoted from `strategy`'s `BacktestBroker`. It depends on `ingest` and `strategy` (it reuses `strategy.core.models.Order` and `strategy.core.portfolio.Portfolio` directly rather than redefining them).

## Commands

Run these from the repo root, not from inside `packages/execution`.

- Run all tests for this package: `uv run pytest packages/execution/tests`
- Run a single test: `uv run pytest packages/execution/tests/core/test_risk_pipeline.py::test_name`
- Type check: `uv run mypy packages/execution`
- Lint: `uv run ruff check packages/execution`

## Architecture

- `core/interfaces.py` defines `RiskCheck` (Protocol) and `RiskResult` (frozen dataclass: `passed` plus an optional `reason`). `RiskCheck.check()` takes `reference_price` as an explicit argument, since `Order` carries no price for market orders — notional/collar checks cannot read a price off the order itself.
- `core/risk_pipeline.py`'s `RiskPipeline.check()` runs checks in order and short-circuits on the first failure, returning that check's `RiskResult`. If every check passes, it returns a shared `_PASS` singleton. `RiskPipeline.from_config()` builds a pipeline from config (see `config/risk.yaml`) using `RiskCheckFactory`.
- `core/registry.py` holds the name-to-class registry for risk checks, same self-registration pattern as the other packages. Checks register with `@register_risk_check("name")`.
- `core/order_state.py` tracks order lifecycle state.
- `core/bar_aggregator.py`'s `TickBarAggregator` converts a live tick stream into bars, feeding the same downstream consumers that backtest bars feed.
- `risk_checks/` holds one check per file: `duplicate_order.py`, `max_daily_loss.py`, `max_order_notional.py`, `max_position_size.py`, `order_rate_limiter.py`, `price_collar.py`. Each self-registers via `core/registry.py`.
- `brokers/paper/broker.py` is the paper-trading `Broker` implementation, promoted from `strategy`'s `BacktestBroker`. It is a distinct class from `strategy/backtest/broker.py` — keep live/paper-trading-only concerns here, not in the backtest broker.
- `config/risk.yaml` is the declarative config for which risk checks run and their thresholds, loaded via `RiskPipeline.from_config()` rather than hardcoded.

## Adding a new risk check

1. Create `risk_checks/<name>.py`, implement the `RiskCheck` protocol from `core/interfaces.py`.
2. Decorate the class with `@register_risk_check("<name>")`.
3. Add its config entry to `config/risk.yaml`.
