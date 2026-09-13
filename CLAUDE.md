# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A quant trading platform built OpenClaw-style: a Claude Code plugin (`plugin/`) is the entire product. There is no separate backend service, no multi-package Python workspace, and no MCP server sitting between the agent and the math. A skill's own script does the mechanics (auth, data fetch, storage); the skill's `SKILL.md` does all orchestration and decision-making; a small shared library holds only the deterministic math that would otherwise be duplicated across skills.

This is a deliberate architectural pivot away from an earlier, framework-heavy design (four Python packages - `ingest`, `quant`, `strategy`, `engine` - each with its own registry/`Protocol`/factory pattern, exposed to skills through one shared MCP server). That design accumulated real, working code that no longer had a reason to exist once the product's actual interactive layer was skills, not a service. See `docs/superpowers/specs/2026-09-12-openclaw-flat-scripts-design.md` for the full rationale and `docs/superpowers/plans/2026-09-12-flat-scripts-migration.md` for how the migration was executed.

Kite Connect is the one data source wired in (Groww is deferred - see `plugin/skills/connect-adapter/SKILL.md`).

## Core stack decision

**Python only**, run as flat scripts via `uv`, not as an installed package. There is no `pyproject.toml` workspace, no `packages/` directory, no `src/` layout with a build step. `uv run python plugin/skills/<name>/scripts/<name>.py` is how every skill's mechanics actually execute.

## Toolchain

- **uv**, Python 3.13. `uv sync` installs the runtime dependencies declared in the root `pyproject.toml` (`httpx`, `duckdb`, `pandas`, `numpy`, `scipy`, `python-dotenv`, `ta`) plus the dev dependency group (`pytest`, `mypy`, `ruff`, etc.). There is nothing else to build or install - no wheel, no editable package.
- **mypy --strict** and **ruff** must pass clean on `plugin/` before a change is considered done. No bare `except`, full type coverage on public functions.
- **No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict anywhere in `plugin/`.** This is not a style preference, it is the point of the architecture: a new technical indicator is one new function plus one new entry in a skill script's own plain `dict[str, Callable]` dispatch table, never a decorator that hides the wiring. If you find yourself reaching for a registry pattern to add something, stop - that is the framework this repo deliberately does not have.
- Every literal that appears in more than one place (provider names, table names, base URLs) belongs in `plugin/lib/mechanics/kite.py` (mechanics constants), imported everywhere it is used, never re-typed inline. Every indicator threshold/window/period is a keyword parameter with a default, never a closed-over constant.

## Commands

Run these from the repo root.

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one skill's or lib area's tests: `uv run pytest plugin/lib/tests/math/indicators` or `uv run pytest plugin/skills/technical-screen/scripts/tests`
- Run a single test: `uv run pytest plugin/lib/tests/math/indicators/test_trend.py::test_compute_sma_averages_last_n_closes`
- Type check: `uv run mypy plugin`
- Lint: `uv run ruff check plugin`
- Run a skill's script directly (what a skill's own instructions do): `uv run python plugin/skills/fetch-bars/scripts/fetch_bars.py --symbol RELIANCE --days 365`

## Repo structure and how it fits together

```
plugin/
  lib/
    mechanics/   flat I/O: Kite OAuth exchange, historical fetch, DuckDB bars store, credential
                 store, NSE index-constituent fetch with a local cache
    math/        flat computation: the indicators/ package (trend, momentum, volatility, volume,
                 structure, cross_sectional) and position_sizing.py
    tests/       tests for everything under lib/
  skills/
    connect-adapter/    SKILL.md + scripts/connect_adapter.py
    fetch-bars/         SKILL.md + scripts/fetch_bars.py
    research/           SKILL.md (calls fetch-bars's script, then the research-agent subagent)
    technical-screen/   SKILL.md + scripts/technical_screen.py
    position-sizing/    SKILL.md + scripts/position_sizing.py
    scan-market/        SKILL.md only (pure orchestration, no script)
  references/    plain-text domain knowledge (indicator formulas, Kite app setup, install steps)
                 - read by a skill when it needs context, never code
  agents/        the research-agent subagent definition
  assets/        plugin metadata assets
  .claude-plugin/  marketplace manifest
  .mcp.json        the one remaining MCP server, Exa web search for the research and scan-market
                   skills - not a server for this repo's own tools, those are gone
```

- `plugin/lib/mechanics/` - Kite OAuth exchange (`kite.py`), the DuckDB bars store (`store.py`, bars table only), the `Bar` dataclass (`models.py`), the home-scoped credential store (`state.py`, `~/.quant-plugin/credentials.duckdb`), and NSE index-constituent fetch with a local cache (`nse_index.py`, used only when a scan-market run names a universe scope). Each is a flat module: functions and one or two plain classes, no interface layer between a skill script and the mechanics it calls.
- `plugin/lib/math/` - every deterministic computation. `indicators/` is organized by category: `trend.py`, `momentum.py`, `volatility.py`, `volume.py` are thin, tested wrappers around [`ta`](https://github.com/bukosabino/ta) wherever it has an equivalent; `structure.py` and `cross_sectional.py` are hand-rolled, since `ta` has no equivalent for either. Every wrapped `ta` reading returns a `TrailingReading` (`_common.py`): the latest value plus a short trailing window, not a bare number. `position_sizing.py` holds `suggest_stop_distance`/`suggest_position_size`/`suggest_take_profit`.
- `plugin/skills/<name>/scripts/<name>.py` - one thin CLI entry point per skill. Parses its own arguments, imports the `plugin/lib` functions it needs, prints one JSON object to stdout. A skill's dispatch-by-name (which indicator) is a plain dict literal inside that script, built and read in one place. `scan-market` has no script of its own - its `SKILL.md` orchestrates the other skills directly, in one conversation, with no subagent spawn.
- `plugin/skills/<name>/SKILL.md` - all orchestration: which script to run, how to interpret its JSON output, what to do on each documented error, how to phrase the result in plain language. This is unchanged in role from before the migration - these files never contained framework code.
- `plugin/references/` - `scan-market.md` (every indicator's formula and typical use, plus the position-sizing formulas), `kite-app-setup.md`, `install.md`.

## What is deliberately not here

Paper/live trading, a risk-check pipeline, order/ledger/equity-curve persistence, and a persistent trade ledger/learning-from-history feature all remain undesigned against this flat-script shape - if wanted later, they get designed fresh, not bolted onto the current skills. `scan-market` proposes trades; it does not place orders.

## Adding a new technical indicator

There is no registration step.

1. Check whether [`ta`](https://github.com/bukosabino/ta) already has the indicator (grep its module source, don't re-derive a formula a maintained library already implements).
2. If it does, add a thin wrapper to the matching category module (`trend.py`, `momentum.py`, `volatility.py`, or `volume.py`), following `compute_sma`'s pattern in `trend.py`: parameter names match `ta`'s own exactly, return a `TrailingReading` (or a small frozen dataclass of them) via `_trailing_reading`.
3. If `ta` has no equivalent, hand-roll it in `structure.py` or `cross_sectional.py`, following an existing function's pattern there.
4. Either way, give every threshold/window a keyword parameter with a default - never close over a fixed value. Add a test in `plugin/lib/tests/math/indicators/`, hand-computed or hand-traced, never asserted by inspection.
5. Wire it into `technical-screen`'s script's `_SINGLE_SERIES_INDICATORS` or `_CROSS_SECTIONAL_INDICATORS` dict.
6. Update `plugin/references/scan-market.md` with the new formula/params so a skill can describe it to the user.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs - sequencing is by dependency, not by timeline.
- Trend/momentum/volatility/volume indicators wrap `ta` rather than being hand-rolled - adopted after a hand-traced fixture caught a real off-by-one bug in a draft hand-rolled Parabolic SAR implementation. Structure and cross-sectional indicators stay hand-rolled, since `ta` has no equivalent for either.
- No `Protocol`/registry/factory pattern gets added back to `plugin/lib/`. If a future feature seems to need one, that is a signal to reconsider the feature's shape, not to reintroduce the framework this repo moved away from.
