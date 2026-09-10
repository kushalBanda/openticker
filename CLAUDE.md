# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A quant trading platform being built from scratch: DataEngine, Strategy/Backtest Engine, Quant Research Layer, plus a Claude Code plugin layer for the AI-native, interactive pieces — see `docs/HLD/Parent-HLD.md` for the full system map, and `docs/HLD/sub/` for each component's detailed HLD. This superseded the repo's earlier framing as an interview-prep curriculum for elite quant firms, the goal now is to actually build and run the product, learning production engineering practice along the way rather than studying it in isolation. The phase folders (01-05) from the old curriculum framing have been removed. Kite Connect and Groww (Indian market data, notes in `docs/dataConnect/`) are the two data sources wired in so far, Upstox is deferred.

Design spec (historical, superseded by the HLD docs above): `docs/superpowers/specs/2026-08-30-elite-quant-curriculum-design.md`

## Core stack decision

**Python only.** The platform is built end to end in Python, no C++ port planned. This is a deliberate change from the repo's original interview-prep framing (which targeted C++ + Python to match firms like Optiver, Jump, HRT, Citadel Securities) since the focus is now on shipping the actual product, not on interview-specific language practice.

## Toolchain

- **uv**, Python 3.13, dependency management and running. `uv sync` to install, `uv run pytest`/`uv run mypy`/`uv run ruff check` to verify.
- **uv workspace**, not a flat single package and not separate repos per component. Each component lives at `packages/<component>/` with its own `pyproject.toml`, own dependencies, source under `src/<component>/`, tests under `packages/<component>/tests/`. Root `pyproject.toml` is the workspace root (`[tool.uv.workspace] members = ["packages/*"]`). Rationale recorded in `docs/HLD/Parent-HLD.md`'s "Repo strategy" section, components have genuinely different dependency sets and this keeps each one lean while staying in one repo.
- **mypy --strict** and **ruff** must pass clean on every component before a slice is considered done. No bare `except`, full type coverage on public APIs.
- Every literal that appears in more than one place within a component (provider names, table names, base URLs, rate limits, header values, HTTP status codes) belongs in that component's `core/constants.py`, imported everywhere it's used, never re-typed inline. Use stdlib `http.HTTPStatus` for status codes rather than raw integers.
- Provider-specific translation tables (Kite's interval strings, Groww's interval minutes, and anything similar a new provider will need) do NOT belong in `core/constants.py` even though they're "constants" — that just relocates the scaling problem, `constants.py` would grow one dict per provider forever. Instead each provider owns its table in its own adapter package (e.g. `adapters/kite/intervals.py`), self-registered into a small generic registry in `core/` (see `core/intervals.py`'s `register_interval_map`/`to_provider_interval`), the same registry pattern already used for adapters themselves. A new provider adds one file to its own package and changes nothing in `core/`.

## Commands

Run these from the repo root.

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one package's tests: `uv run pytest packages/<component>/tests`
- Run a single test: `uv run pytest packages/<component>/tests/path/to/test_file.py::test_name`
- Type check (whole workspace, config is at root `pyproject.toml`): `uv run mypy`
- Type check one package: `uv run mypy packages/<component>`
- Lint: `uv run ruff check` (or `uv run ruff check packages/<component>` for one package)

## Repo structure and how it fits together

Phase folders (01-05) were removed for a revamp. Fixed pieces so far, each with its own `CLAUDE.md` for package-specific detail:

- `packages/ingest/` (formerly `data_engine`) — first component built, ingests market data via pluggable provider adapters (Kite Connect, Groww) into DuckDB. See `packages/ingest/CLAUDE.md` and `docs/plans/data-engine/` for its 4-gate design docs and slice-by-slice build status.
- `packages/quant/` — Quant Research Layer: signals, forecast scaling, position sizing. Depends on `ingest`. See `packages/quant/CLAUDE.md`.
- `packages/strategy/` — hand-built bar-by-bar backtest engine with pluggable strategies. Depends on `ingest` and `quant`. See `packages/strategy/CLAUDE.md`.
- All three packages above share the same self-registering-registry pattern for their pluggable pieces (adapters, signals, strategies) — a `core/registry.py` with a decorator (`@register_*`) and a `*Factory`/`get_*_class` lookup, so `core/` never has to import concrete implementations by name.
- **Deprecated and removed** (were `packages/execution`, `packages/server`, `packages/agents`): a pre-trade risk pipeline/paper broker, a FastAPI REST layer, and a litellm-based LLM advisor for in-loop strategy-param tuning. None had a real dependent once the plugin (below) became the interactive layer — Claude Code itself is now the harness and the model, so a separate REST API and a separate LLM-advisor package were redundant. The pairs-trading strategy's optional `advisor` hook (which imported `packages/agents`) was stripped back to its always-rule-based path when `agents` was deleted; no feature the plugin used was lost. If paper trading or a hosted REST API are needed again later, they get re-designed against the plugin-first architecture, not restored as-is.
- `docs/HLD/Parent-HLD.md` and `docs/HLD/sub/` — high-level design for every component, read before starting work on a new one.
- `docs/resources/` — cloned reference repos (e.g. `Kronos`, `TradingAgents`, `backtesting.py`, `gs-quant`) kept as read-only architecture study material. Gitignored (`docs/resources/*/`) — never treat these as vendored dependencies of this repo, and never edit files inside them.
- `docs/dataConnect/Kite/` and `docs/dataConnect/Groww/` — API notes (auth, historical/live data, rate limits) for the two data providers wired in so far. Any data-engine adapter work should reference these notes.

## v2: Claude Code plugin layer

A second, separate deployment target sits alongside the `packages/*` workspace: a Claude Code plugin at `plugin/` (repo root), distributed by cloning this repo — not a hosted SaaS, not a `/plugin install` from a public marketplace yet.

- Claude Code is the interactive harness (skills, subagents, orchestration). It is not a replacement for `packages/*`'s actual computation — an LLM cannot itself be a deterministic backtest engine or a rate-limited data pipeline. `packages/*` (now just `ingest`, `quant`, `strategy`) stays the real backend; the plugin is the interactive layer on top of it.
- The plugin never depended on `packages/server`'s REST + JWT layer, and that package (plus `packages/execution` and `packages/agents`) has since been deleted — see the "Deprecated and removed" note above. `plugin/scripts/*.py` call directly into `packages/ingest`, `packages/quant`, and `packages/strategy` (via `uv run python ...` from `${CLAUDE_PROJECT_DIR}`).
- No persistent background process. The one exception: Kite's OAuth login inherently needs a local HTTP redirect target, so the connect flow spins up a short-lived listener for that one exchange and shuts it down immediately — not a daemon.
- Plugin-local state (raw provider credentials, later a run cache) lives in a home-scoped SQLite store, `~/.quant-plugin/state.db` (WAL mode, 0600 permissions) — never project-scoped, so it survives a repo re-clone. This is separate from and unrelated to `packages/ingest`'s DuckDB market-data store.
- A self-registering `.claude-plugin/marketplace.json` plus a committed `.claude/settings.json` (`extraKnownMarketplaces` + `enabledPlugins`) declare the plugin, but install is not fully automatic — Claude Code still requires accepting a one-time workspace-trust prompt, then running `/plugin install quant-platform@quant-platform-marketplace` once (see `plugin/references/install.md`). This is a Claude Code security boundary, not something this plugin can bypass.
- Bundles the Exa Web MCP server (`.mcp.json`, optional `EXA_API_KEY`) alongside Claude's own built-in web search, for the research agent's outside-context lookups.
- Build plan: tracer-bullet tickets in `docs/v2/quant-plugin/issues/`, numbered in dependency order. Built and live-verified against a real Kite session: skeleton, local credential store, Kite connect, a fetch-bars skill, the research agent, and a run-backtest skill (ticket 06) wrapping `packages/strategy`/`packages/quant` the same way `fetch_bars.py` wraps `ingest` — see `plugin/references/strategies.md` and `plugin/references/quant-signals.md`. Groww (ticket 04) is deliberately deferred (p2) — `AdapterFactory` is already provider-agnostic, so adding it later is additive, not a redesign. The fuller agent catalog (a judge/decision agent, a trader/proposal agent) is deferred until real usage on this slice justifies it.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs — sequencing is by dependency, not by timeline. This was an explicit user requirement.
- The Strategy/Backtest Engine (see `docs/HLD/sub/strategy-backtest-engine.md`) is meant to be hand-built, not swapped for an off-the-shelf backtesting library — the point is production-grade engineering practice, not the fastest path to a working backtest.
