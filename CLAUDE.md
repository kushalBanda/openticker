# CLAUDE.md

Guidance for Claude Code (and other coding agents) working in this repository. Maintainers may also have a gitignored `CLAUDE.local.md` with private workflow notes.

## What this repo is

**OpenTicker**: a self-hosted, agent-operated trading platform for Indian markets. An MCP client (Claude Code, Codex, ...) operates it directly through tool calls: connect a broker, sync instruments, search symbols, fetch quotes, historical bars and option chains with Greeks, and paper trade in a local sandbox. The same operations are served over a REST API with API keys (`openticker-serve`, ADR 17), which also streams live prices from the broker. A market calendar keeps orders to open sessions. Risk rules, an audit log and notifications are built. Options strategies can be defined and previewed (ADR 20), then started by hand or on a schedule (ADR 22): that server enters them in the sandbox and watches them unattended (ADR 21), falls back to quotes when the feed goes quiet, stops a run whose prices are lost, and reconciles runs after a restart (ADR 23). Alert-driven strategies and user Python scripts are planned (ADRs 12-15). No web UI yet.

Design decisions and their reasoning live in `docs/adr/` (`1. hexagonal-architecture.md` onward). Read the relevant ADR before changing an area; add a new ADR when making a decision a future contributor would otherwise have to reverse-engineer.

## Core stack

**Python 3.13, `src/` layout, `uv`.** `uv sync` installs everything. Entry points: `openticker-mcp` (MCP over stdio, spawned per agent session, no port) and `openticker-serve` (long-running REST server, plus `keys create|list|revoke`).

Key libraries: `mcp` (the SDK is 2.x: `FastMCP` was renamed `MCPServer`, import from `mcp.server.mcpserver`, not the `fastmcp` path most examples online show), `pydantic` (result models at the MCP and REST edges only), `fastapi` + `uvicorn` (REST), `sqlalchemy` (SQLite), `duckdb` (bars), `httpx` (sync client), `cryptography` (Fernet, credentials encrypted at rest), `python-dotenv`.

## Architecture (hexagonal, ADR 1)

```
core/         domain logic. Zero I/O, zero framework imports. orders/ (order shapes, validation, sandbox fill and margin math, resting-order matching), risk/ (position risk rules, strategy-wide rules over several legs), options/ (Black-76 Greeks, chains, ADR 16), calendar/ (trading days and session hours, ADR 13), strategies/ (strategy definitions and leg resolution, ADR 20; runs, their legs and ratchets, ADR 21; schedule.py, when entries and exits are due, ADR 22; prices.py, when a leg's price needs polling or is stale, ADR 23).
ports/        Protocol interfaces, shared DTOs (models.py), shared errors (errors.py).
adapters/     implementations: brokers/ (registry + zerodha/, including the WebSocket feed), sandbox/ (paper trading, ADR 11), notifications/ (slack, email), inbound/ (mcp_server.py, mcp_models.py, rest_api.py, daemon/: main.py entry point, feed_loop.py, execution_loop.py, strategy_loop.py, quote_poller.py, prices.py).
use_cases/    one flat function per operation, not a class. May call storage directly; publish events. strategies/ groups the strategy operations: define.py (definitions), control.py (commands), runner.py (the daemon's side, ADR 21; scheduled starts, ADR 22; reconciling orders with the sandbox, ADR 23).
events/       EventBus, event types, subscribers (audit_log inline, notifications background), ADR 10.
composition.py  builds the event bus, notification channels and the sandbox (`order_broker`) from env. The only place they're wired.
storage/      sqlite/ (transactional state), duckdb/ (bars), ADR 3; calendar_file.py (shipped `data/holidays.json`, overridable at `$OPENTICKER_HOME/holidays.json`).
```

Dependencies point inward: `adapters -> ports <- use_cases -> core`. Nothing in `core/` or `ports/` imports from `adapters/` or `use_cases/`.

- **`Protocol`, not `ABC`, for every port** (ADR 1).
- **One broker registry**: `adapters/brokers/registry.py` maps broker names to adapter builders and login-URL builders. Inbound adapters never special-case a broker name; they call `get_adapter()` / `get_login_url()`.
- **Frozen dataclasses in `core/` and `ports/`.** Pydantic exists only at the inbound edge: `mcp_models.py` (shared by MCP and REST) and request bodies in `rest_api.py`.
- **Sync, not async, throughout `core/` and `use_cases/`**, and SQLite always via `NullPool` (ADR 2). Don't "fix" either.
- **A `BrokerPort` implementation must satisfy the full Protocol**: methods not wired yet raise `NotImplementedError("<what> is not implemented yet")`.
- **Broker errors derive from `ports.errors.BrokerError`** with messages that say how to recover. The MCP edge turns agent-fixable errors into `ToolError`; anything else stays an opaque crash (ADR 7).
- **Every MCP tool has a REST route** returning the same result model (ADR 17); `test_every_mcp_tool_has_a_rest_route` enforces it. REST maps the same agent-fixable errors to 404/502/503.
- **MCP tools follow ADR 8**: title, annotations, every parameter described, Pydantic result model, bounded responses. `test_every_tool_is_fully_described_for_agents` fails any tool that doesn't.
- **Times**: stored and passed around as tz-aware UTC; returned to agents exchange-local (`+05:30`). Input dates are exchange-local trading dates (ADR 3).
- **Importing a module must be side-effect-free.** `load_dotenv()` runs only in the entry points' `main()` (`mcp_server`, `daemon/main`).
- **Risk rules are pure functions** in `core/risk/` (ADR 9 per position, ADR 19 per strategy): absent prices are `None`/0 and never defaulted, direction is `side` never a signed quantity, stop loss beats target.
- **Side effects go through events** (ADR 10): use cases publish, subscribers audit and notify. Never call a notification channel from a use case.
- **Anything time-dependent takes the clock as a parameter** (`now`, or a `clock` callable at the edges: `mcp_server.clock`, `create_app(clock=...)`). Tests pin it to a trading time; nothing reads the wall clock deep inside.
- **Live prices come through `MarketFeedPort`** (ADR 13). `ticks()` raises `BrokerSessionError` when the broker refuses the session; `FeedLoop` turns that into one `BrokerSessionExpired` event. Never log the Kite ticker URL: it carries the access token.
- **Schema changes are additive** (ADR 18): a new column on an existing table must be nullable, and readers treat NULL as its default. `get_engine()` adds it to old databases. Anything else needs a real migration.
- **Strategy control is a command** (ADR 12, ADR 21): MCP and REST write `strategy_commands` rows; only the daemon's runner places strategy orders, recording each in `strategy_orders` before sending it. A running strategy is never edited or deleted.
- **Order placement is sandbox-only** (ADR 6, ADR 11): `SandboxBroker` wraps the real broker adapter for prices; broker adapters' order methods raise `NotImplementedError`. Sandbox fills go through `sandbox_repo.fill_transaction()` (`BEGIN IMMEDIATE`). Resting orders are filled by the daemon through `SandboxPort` (`use_cases/execute_resting_orders.py`); intraday square-off is `use_cases/square_off.py`; expiry settlement is `use_cases/settle_expired.py` (price rules in `core/orders/settlement.py`).
- **Code comments reference ADRs, never internal planning docs.** This repo is public.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest`
- Type check (must pass clean, strict): `uv run mypy src tests`
- Lint: `uv run ruff check src tests`
- Run the MCP server: `uv run openticker-mcp`
- Run the REST server: `uv run openticker-serve` (create a key first: `uv run openticker-serve keys create <name>`)

## Tests

`tests/` mirrors `src/openticker/`. `tests/conftest.py` gives every test its own `OPENTICKER_HOME`, so nothing touches `~/.openticker`. `tests/fixtures/fake_broker.py` (`FakeBrokerPort`) is a network-free broker; MCP tool tests register it under the name `"fake"` and exercise the full tool -> registry -> use case -> storage path. HTTP in adapter tests is faked by monkeypatching `httpx`.

## Secrets

`.env` (gitignored) holds broker API credentials. Never print or commit its values. Broker session tokens are stored Fernet-encrypted and never returned by any tool (ADR 5).
