# CLAUDE.md — packages/ingest

This file gives guidance for work inside `packages/ingest`. Read the root `/CLAUDE.md` first for workspace-wide rules.

## What this package does

`ingest` (formerly `data_engine`) ingests historical and live market data through pluggable provider adapters. It stores bars and ticks in DuckDB. Two providers are wired in: Kite Connect and Groww. Notes on both providers are in `docs/dataConnect/Kite/` and `docs/dataConnect/Groww/` at the repo root.

**Login status:** Kite has a real OAuth-style redirect login (`server/routers/auth.py`'s `/auth/kite/login` + `/auth/kite/callback`) — the app registers once with Zerodha for one `api_key`/`api_secret` pair, and each end user authenticates on Zerodha's own login page, never pasting a key. Groww has no published app-registration + redirect flow; `/auth/groww/login` still requires the end user to generate their own `api_key`/`api_secret` (or `totp_secret`) in their own Groww account and paste it in — work in progress, pending confirmation from Groww on whether a partner-style flow exists outside the public docs. Kite is the provider the SaaS positioning leans on for now.

## Commands

Run these from the repo root, not from inside `packages/ingest`.

- Run all tests for this package: `uv run pytest packages/ingest/tests`
- Run a single test file: `uv run pytest packages/ingest/tests/test_engine.py`
- Run a single test: `uv run pytest packages/ingest/tests/test_engine.py::test_name`
- Type check: `uv run mypy packages/ingest`
- Lint: `uv run ruff check packages/ingest`

## Architecture

- `core/interfaces.py` defines the `MarketDataAdapter` protocol. Every provider adapter must implement it.
- `core/registry.py` holds a name-to-class registry for adapters. Each adapter self-registers with `@register_adapter("name")`. `core/engine.py`'s `DataEngine` resolves adapters by provider name at call time, it does not import adapter classes directly.
- `core/intervals.py` holds a separate generic registry for interval translation, `register_interval_map` / `to_provider_interval`. Each provider maps its own interval strings (e.g. Kite's `"minute"`, `"day"`) to the canonical bar interval. Provider interval tables live in the provider's own package (`adapters/kite/intervals.py`, `adapters/groww/intervals.py`), never in `core/constants.py`.
- `core/provider_routes.py` and `core/rate_limiter.py` support routing a symbol to its default provider and enforcing provider-specific rate limits.
- `adapters/kite/` and `adapters/groww/` each hold an `adapter.py` (implements `MarketDataAdapter`), a `mapper.py` (translates provider payloads to `core/models.py` types, `Bar`/`Tick`), and an `intervals.py` (this provider's interval table).
- `adapters/kite/instrument_master.py` handles Kite's instrument token lookup, a Kite-specific concern with no Groww equivalent.
- `storage/duckdb_store.py` is the single DuckDB-backed persistence layer, used by `DataEngine` for both bars and ticks.
- `config/` holds provider config (e.g. rate limits, routes) loaded at startup, not hardcoded.

## Adding a new provider

1. Create `adapters/<provider>/` with `adapter.py`, `mapper.py`, `intervals.py`.
2. Implement `MarketDataAdapter` in `adapter.py`, decorate the class with `@register_adapter("<provider>")`.
3. Register the interval table in `intervals.py` via `register_interval_map`.
4. Do not touch `core/` — the registry pattern means `core/` never needs to know about a new provider by name.

## Deliberate design choices

- Provider-specific translation tables (interval strings, etc.) live in each adapter's own package, not in `core/constants.py`. Putting them in `constants.py` would make that file grow one dict per provider forever.
- A raw `BLE001` (blind except) is allowed in `adapters/groww/adapter.py` only, inside Groww's NATS feed background-thread callback — anything raised there would otherwise vanish silently instead of surfacing through `DataEngine`'s queue. Do not "fix" this by removing the exception, and do not copy this exemption to other files without the same justification.
