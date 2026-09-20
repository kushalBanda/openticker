# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Flat Kite Connect mechanics: OAuth login and historical bar fetch, backed by a local DuckDB store. No Claude Code plugin, no skills layer, no separate backend service, no multi-package Python workspace, no MCP server. Two CLI scripts under `scripts/` are the only entry points; a small shared library under `lib/` holds the mechanics they call into.

Kite Connect is the one data source wired in.

## Core stack decision

**Python only**, run as flat scripts via `uv`, not as an installed package. There is no `packages/` directory, no `src/` layout with a build step. `uv run python scripts/<name>.py` is how everything actually executes.

## Toolchain

- **uv**, Python 3.13. `uv sync` installs the runtime dependencies declared in the root `pyproject.toml` (`httpx`, `duckdb`, `pytz`, `python-dotenv`) plus the dev dependency group (`pytest`, `mypy`, `ruff`, etc.). There is nothing else to build or install - no wheel, no editable package.
- **mypy --strict** and **ruff** must pass clean before a change is considered done. No bare `except`, full type coverage on public functions.
- **No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict anywhere in `lib/`.** This is not a style preference, it is the point of the architecture. If you find yourself reaching for a registry pattern, stop - that is the framework this repo deliberately does not have.
- Every literal that appears in more than one place (provider names, table names, base URLs) belongs in `lib/mechanics/kite.py` (mechanics constants), imported everywhere it is used, never re-typed inline.

## Commands

Run these from the repo root.

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest lib/tests/mechanics/test_store.py::test_write_and_query_round_trip`
- Type check: `uv run mypy lib scripts`
- Lint: `uv run ruff check lib scripts`
- Connect a broker: `uv run python scripts/connect_adapter.py`
- Fetch bars: `uv run python scripts/fetch_bars.py --symbol RELIANCE --days 365`

## Repo structure and how it fits together

```
lib/
  mechanics/   flat I/O: Kite OAuth exchange, historical fetch, DuckDB bars store, credential store
  tests/       tests for everything under lib/
scripts/
  connect_adapter.py   Kite OAuth login CLI
  fetch_bars.py        historical OHLCV bars CLI
  tests/               tests for the scripts above
references/    plain-text domain knowledge (Kite app setup)
```

- `lib/mechanics/` - Kite OAuth exchange (`kite.py`), the DuckDB bars store (`store.py`, bars table only), the `Bar` dataclass (`models.py`), the home-scoped credential store (`state.py`, `~/.quant-plugin/credentials.duckdb`), shared exceptions (`exceptions.py`). Each is a flat module: functions and one or two plain classes, no interface layer between a script and the mechanics it calls.
- `scripts/<name>.py` - one thin CLI entry point. Parses its own arguments, imports the `lib` functions it needs, prints one JSON object to stdout.
- `references/` - `kite-app-setup.md`.

## What is deliberately not here

A Claude Code plugin/skills layer, technical indicators, position sizing, research reports, market scanning, paper/live trading, a risk-check pipeline, order/ledger/equity-curve persistence, and a persistent trade ledger all remain undesigned against this flat-script shape - if wanted later, they get designed fresh, not bolted onto the current scripts.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs - sequencing is by dependency, not by timeline.
- No `Protocol`/registry/factory pattern gets added back to `lib/`. If a future feature seems to need one, that is a signal to reconsider the feature's shape, not to reintroduce the framework this repo moved away from.
