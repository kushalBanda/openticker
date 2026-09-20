# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A quant trading platform built OpenClaw-style: a Claude Code plugin (`plugin/`) is the entire product. There is no separate backend service, no multi-package Python workspace, and no MCP server sitting between the agent and the mechanics. A skill's own script does the mechanics (auth, data fetch, storage); the skill's `SKILL.md` does all orchestration and decision-making.

Kite Connect is the one data source wired in (Groww is deferred - see `plugin/skills/connect-adapter/SKILL.md`).

## Core stack decision

**Python only**, run as flat scripts via `uv`, not as an installed package. There is no `pyproject.toml` workspace, no `packages/` directory, no `src/` layout with a build step. `uv run python plugin/skills/<name>/scripts/<name>.py` is how every skill's mechanics actually execute.

## Toolchain

- **uv**, Python 3.13. `uv sync` installs the runtime dependencies declared in the root `pyproject.toml` (`httpx`, `duckdb`, `pytz`, `python-dotenv`) plus the dev dependency group (`pytest`, `mypy`, `ruff`, etc.). There is nothing else to build or install - no wheel, no editable package.
- **mypy --strict** and **ruff** must pass clean on `plugin/` before a change is considered done. No bare `except`, full type coverage on public functions.
- **No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict anywhere in `plugin/`.** This is not a style preference, it is the point of the architecture. If you find yourself reaching for a registry pattern, stop - that is the framework this repo deliberately does not have.
- Every literal that appears in more than one place (provider names, table names, base URLs) belongs in `plugin/lib/mechanics/kite.py` (mechanics constants), imported everywhere it is used, never re-typed inline.

## Commands

Run these from the repo root.

- Install dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run a single test: `uv run pytest plugin/lib/tests/mechanics/test_store.py::test_write_and_query_round_trip`
- Type check: `uv run mypy plugin`
- Lint: `uv run ruff check plugin`
- Run a skill's script directly (what a skill's own instructions do): `uv run python plugin/skills/fetch-bars/scripts/fetch_bars.py --symbol RELIANCE --days 365`

## Repo structure and how it fits together

```
plugin/
  lib/
    mechanics/   flat I/O: Kite OAuth exchange, historical fetch, DuckDB bars store, credential store
    tests/       tests for everything under lib/
  skills/
    connect-adapter/    SKILL.md + scripts/connect_adapter.py
    fetch-bars/         SKILL.md + scripts/fetch_bars.py
  references/    plain-text domain knowledge (Kite app setup) - read by a skill when it needs
                 context, never code
  .claude-plugin/  marketplace manifest
```

- `plugin/lib/mechanics/` - Kite OAuth exchange (`kite.py`), the DuckDB bars store (`store.py`, bars table only), the `Bar` dataclass (`models.py`), the home-scoped credential store (`state.py`, `~/.quant-plugin/credentials.duckdb`), shared exceptions (`exceptions.py`). Each is a flat module: functions and one or two plain classes, no interface layer between a skill script and the mechanics it calls.
- `plugin/skills/<name>/scripts/<name>.py` - one thin CLI entry point per skill. Parses its own arguments, imports the `plugin/lib` functions it needs, prints one JSON object to stdout.
- `plugin/skills/<name>/SKILL.md` - all orchestration: which script to run, how to interpret its JSON output, what to do on each documented error, how to phrase the result in plain language.
- `plugin/references/` - `kite-app-setup.md`.

## What is deliberately not here

Technical indicators, position sizing, research reports, market scanning, paper/live trading, a risk-check pipeline, order/ledger/equity-curve persistence, and a persistent trade ledger all remain undesigned against this flat-script shape - if wanted later, they get designed fresh, not bolted onto the current skills.

## Explicit constraints (deliberate, do not "fix")

- No week/time estimates anywhere in phase docs or specs - sequencing is by dependency, not by timeline.
- No `Protocol`/registry/factory pattern gets added back to `plugin/lib/`. If a future feature seems to need one, that is a signal to reconsider the feature's shape, not to reintroduce the framework this repo moved away from.
