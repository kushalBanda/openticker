# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A quant trading platform built OpenClaw-style: a Claude Code plugin (`plugin/`) is the entire product. There is no separate backend service, no multi-package Python workspace, and no MCP server sitting between the agent and the math. A skill's own script does the mechanics (auth, data fetch, storage); the skill's `SKILL.md` does all orchestration and decision-making; a small shared library holds only the deterministic math that would otherwise be duplicated across skills.

This is a deliberate architectural pivot away from an earlier, framework-heavy design (four Python packages - `ingest`, `quant`, `strategy`, `engine` - each with its own registry/`Protocol`/factory pattern, exposed to skills through one shared MCP server). That design accumulated real, working code that no longer had a reason to exist once the product's actual interactive layer was skills, not a service. See `docs/superpowers/specs/2026-09-12-openclaw-flat-scripts-design.md` for the full rationale and `docs/superpowers/plans/2026-09-12-flat-scripts-migration.md` for how the migration was executed.

Kite Connect is the one data source wired in (Groww is deferred - see `plugin/skills/connect-adapter/SKILL.md`).

## Core stack decision

**Python only**, run as flat scripts via `uv`, not as an installed package. There is no `pyproject.toml` workspace, no `packages/` directory, no `src/` layout with a build step. `uv run python plugin/skills/<name>/scripts/<name>.py` is how every skill's mechanics actually execute.

## Toolchain

- **uv**, Python 3.13. `uv sync` installs the runtime dependencies declared in the root `pyproject.toml` (`httpx`, `duckdb`, `pandas`, `numpy`, `scipy`, `python-dotenv`) plus the dev dependency group (`pytest`, `mypy`, `ruff`, etc.). There is nothing else to build or install - no wheel, no editable package.
- **mypy --strict** and **ruff** must pass clean on `plugin/` before a change is considered done. No bare `except`, full type coverage on public functions.
- **No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict anywhere in `plugin/`.** This is not a style preference, it is the point of the architecture: a new signal or strategy is one new file plus one new entry in a skill script's own plain `dict[str, Callable]` dispatch table, never a decorator that hides the wiring. If you find yourself reaching for a registry pattern to add something, stop - that is the framework this repo deliberately does not have.
- Every literal that appears in more than one place (provider names, table names, base URLs, bps rates, order-side strings) belongs in `plugin/lib/mechanics/kite.py` (mechanics constants) or `plugin/lib/math/constants.py` (math constants), imported everywhere it is used, never re-typed inline.

## Commands

Run these from the repo root.

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one skill's or lib area's tests: `uv run pytest plugin/lib/tests/math` or `uv run pytest plugin/skills/run-backtest/scripts/tests`
- Run a single test: `uv run pytest plugin/lib/tests/math/test_statistics.py::test_max_drawdown_detects_peak_to_trough`
- Type check: `uv run mypy plugin`
- Lint: `uv run ruff check plugin`
- Run a skill's script directly (what a skill's own instructions do): `uv run python plugin/skills/fetch-bars/scripts/fetch_bars.py --symbol RELIANCE --days 365`

## Repo structure and how it fits together

```
plugin/
  lib/
    mechanics/   flat I/O: Kite OAuth exchange, historical fetch, DuckDB bars store, credential store
    math/        flat computation: indicators, signal evaluation, cost models, the backtest loop,
                 portfolio/ledger accounting, and all 5 strategies under math/strategies/
    tests/       tests for everything under lib/
  skills/
    connect-adapter/   SKILL.md + scripts/connect_adapter.py
    fetch-bars/        SKILL.md + scripts/fetch_bars.py
    evaluate-signal/   SKILL.md + scripts/evaluate_signal.py
    run-backtest/      SKILL.md + scripts/run_backtest.py
    research/          SKILL.md (calls fetch-bars's script, then the research-agent subagent)
  references/    plain-text domain knowledge (formulas, strategy citations, cost-model tables,
                 Kite app setup, install steps) - read by a skill when it needs context, never code
  agents/        the research-agent subagent definition
  assets/        plugin metadata assets
  .claude-plugin/  marketplace manifest
  .mcp.json        the one remaining MCP server, Exa web search for the research skill - not
                   a server for this repo's own tools, those are gone
```

- `plugin/lib/mechanics/` - Kite OAuth exchange (`kite.py`), the DuckDB bars store (`store.py`, bars table only), the `Bar` dataclass (`models.py`), and the home-scoped credential store (`state.py`, `~/.quant-plugin/credentials.duckdb`). Each is a flat module: functions and one or two plain classes, no interface layer between a skill script and the mechanics it calls.
- `plugin/lib/math/` - every deterministic computation, ported formula-for-formula from the deleted `quant`/`strategy` packages with the class/registry wrapping stripped off: `indicators.py` (RSI/SMA/volume/momentum, each a plain `compute_*`/`scale_*` function pair), `evaluation.py` (information-coefficient signal evaluation), `statistics.py`/`econometrics.py`/`pairs.py`/`technicals.py` (the underlying math), `cost_models.py` (real Kite/Groww fee schedules as 4 straight-line functions), `sizing.py`/`portfolio.py`/`broker.py`/`backtest.py`/`performance.py` (position sizing, P&L accounting, the bar-by-bar backtest loop), `triggers.py`/`actions.py` (composable entry/exit building blocks, plain functions/classes, no `Protocol`), and `strategies/` (`sma_cross`, `buy_and_hold`, `mean_reversion`, `pairs_trading`, `time_series_momentum` - all 5 live and reachable).
- `plugin/skills/<name>/scripts/<name>.py` - one thin CLI entry point per skill. Parses its own arguments, imports the `plugin/lib` functions it needs, prints one JSON object to stdout. A skill's dispatch-by-name (which strategy, which signal) is a plain dict literal inside that script, built and read in one place.
- `plugin/skills/<name>/SKILL.md` - all orchestration: which script to run, how to interpret its JSON output, what to do on each documented error, how to phrase the result in plain language. This is unchanged in role from before the migration - these files never contained framework code.
- `plugin/references/` - `quant-signals.md` (signal formulas and the forecast-scaling convention), `strategies.md` (per-strategy params, citations, the no-lookahead rule), `cost-models.md` (the Kite/Groww bps tables), `kite-app-setup.md`, `install.md`.

## What is deliberately not here

Paper/live trading, a risk-check pipeline, order/ledger/equity-curve persistence, a correlation-aware multi-position sizer, and a watchlist/setup/screening layer all existed in the deleted packages with zero live caller from any skill. They were not ported - per the migration spec, if any of these is wanted later it gets designed fresh against this flat-script shape, not resurrected as-is. Index-constituent fetching and live tick storage were dropped the same way.

## Adding a new signal or strategy

There is no registration step.

1. **New signal:** add `compute_<name>`/`scale_<name>` functions to `plugin/lib/math/indicators.py` (or a new module if it needs feature math that doesn't exist yet - add that to `plugin/lib/math/` first). Add a test in `plugin/lib/tests/math/`. Wire it into `evaluate-signal`'s script by adding one entry to that script's `_SIGNAL_COMPUTE` dict.
2. **New strategy:** add `plugin/lib/math/strategies/<name>.py` with a class implementing `on_bar(bars, portfolio, broker)` and a `make_<name>_on_bar(params) -> OnBar` factory, composing `plugin/lib/math/triggers.py`/`actions.py` for its entry/exit logic rather than inlining conditions. Add a test in `plugin/lib/tests/math/strategies/`. Wire it into `run-backtest`'s script by adding one entry to that script's `_STRATEGY_FACTORY` dict.
3. Update `plugin/references/quant-signals.md` or `strategies.md` with the new formula/params so a skill can describe it to the user.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs - sequencing is by dependency, not by timeline.
- The backtest loop (`plugin/lib/math/backtest.py`) is hand-built on purpose, not swapped for an off-the-shelf backtesting library - the point is production-grade engineering practice, not the fastest path to a working backtest.
- No `Protocol`/registry/factory pattern gets added back to `plugin/lib/`. If a future feature seems to need one, that is a signal to reconsider the feature's shape, not to reintroduce the framework this repo moved away from.
