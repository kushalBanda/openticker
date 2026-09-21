# CLAUDE.md

Guidance for Claude Code (and other coding agents) working in this repository. Maintainers may also have a gitignored `CLAUDE.local.md` with private workflow notes.

## What this repo is

**OpenTicker**: a self-hosted, agent-operated trading platform for Indian markets. An MCP client (Claude Code, Codex, ...) operates it directly through tool calls: connect a broker, sync instruments, search symbols, fetch quotes, historical bars and option chains with Greeks. Risk rules, an audit log and notifications are built. Sandbox order placement, an always-on daemon with a REST API, live prices, unattended strategies (rule-based, alert-driven, and user Python scripts) are planned (ADRs 11-15). No web UI yet.

Design decisions and their reasoning live in `docs/adr/` (`1. hexagonal-architecture.md` onward). Read the relevant ADR before changing an area; add a new ADR when making a decision a future contributor would otherwise have to reverse-engineer.

## Core stack

**Python 3.13, `src/` layout, `uv`.** `uv sync` installs everything. Entry point: `openticker-mcp` (MCP over stdio, spawned per agent session, no port).

Key libraries: `mcp` (the SDK is 2.x: `FastMCP` was renamed `MCPServer`, import from `mcp.server.mcpserver`, not the `fastmcp` path most examples online show), `pydantic` (MCP result models only), `sqlalchemy` (SQLite), `duckdb` (bars), `httpx` (sync client), `cryptography` (Fernet, credentials encrypted at rest), `python-dotenv`.

## Architecture (hexagonal, ADR 1)

```
core/         domain logic. Zero I/O, zero framework imports. orders/ (order shapes), risk/ (position risk rules), options/ (Black-76 Greeks, chains, ADR 16).
ports/        Protocol interfaces, shared DTOs (models.py), shared errors (errors.py).
adapters/     implementations: brokers/ (registry + zerodha/), notifications/ (slack, email), inbound/ (mcp_server.py, mcp_models.py).
use_cases/    one flat function per operation, not a class. May call storage directly; publish events.
events/       EventBus, event types, subscribers (audit_log inline, notifications background), ADR 10.
composition.py  builds the event bus and notification channels from env. The only place they're wired.
storage/      sqlite/ (transactional state) and duckdb/ (bars), ADR 3.
```

Dependencies point inward: `adapters -> ports <- use_cases -> core`. Nothing in `core/` or `ports/` imports from `adapters/` or `use_cases/`.

- **`Protocol`, not `ABC`, for every port** (ADR 1).
- **One broker registry**: `adapters/brokers/registry.py` maps broker names to adapter builders and login-URL builders. Inbound adapters never special-case a broker name; they call `get_adapter()` / `get_login_url()`.
- **Frozen dataclasses in `core/` and `ports/`.** Pydantic exists only at the MCP edge (`mcp_models.py`).
- **Sync, not async, throughout `core/` and `use_cases/`**, and SQLite always via `NullPool` (ADR 2). Don't "fix" either.
- **A `BrokerPort` implementation must satisfy the full Protocol**: methods not wired yet raise `NotImplementedError("<what> is not implemented yet")`.
- **Broker errors derive from `ports.errors.BrokerError`** with messages that say how to recover. The MCP edge turns agent-fixable errors into `ToolError`; anything else stays an opaque crash (ADR 7).
- **MCP tools follow ADR 8**: title, annotations, every parameter described, Pydantic result model, bounded responses. `test_every_tool_is_fully_described_for_agents` fails any tool that doesn't.
- **Times**: stored and passed around as tz-aware UTC; returned to agents exchange-local (`+05:30`). Input dates are exchange-local trading dates (ADR 3).
- **Importing a module must be side-effect-free.** `load_dotenv()` runs only in `mcp_server.main()`.
- **Risk rules are pure functions** in `core/risk/` (ADR 9): absent prices are `None`/0 and never defaulted, direction is `side` never a signed quantity, stop loss beats target.
- **Side effects go through events** (ADR 10): use cases publish, subscribers audit and notify. Never call a notification channel from a use case.
- **Order placement is sandbox-only** (ADR 6).
- **Code comments reference ADRs, never internal planning docs.** This repo is public.

## Commands

- Install: `uv sync`
- Tests: `uv run pytest`
- Type check (must pass clean, strict): `uv run mypy src tests`
- Lint: `uv run ruff check src tests`
- Run the MCP server: `uv run openticker-mcp`

## Tests

`tests/` mirrors `src/openticker/`. `tests/conftest.py` gives every test its own `OPENTICKER_HOME`, so nothing touches `~/.openticker`. `tests/fixtures/fake_broker.py` (`FakeBrokerPort`) is a network-free broker; MCP tool tests register it under the name `"fake"` and exercise the full tool -> registry -> use case -> storage path. HTTP in adapter tests is faked by monkeypatching `httpx`.

## Secrets

`.env` (gitignored) holds broker API credentials. Never print or commit its values. Broker session tokens are stored Fernet-encrypted and never returned by any tool (ADR 5).
