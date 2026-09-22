# OpenTicker

**A self-hosted trading platform for Indian markets that AI agents operate directly.**

OpenTicker exposes brokerage operations as [MCP](https://modelcontextprotocol.io) tools. Claude Code, Codex, or any MCP client can connect your broker, find instruments, and pull live quotes and historical candles by calling tools, with no UI in between. It runs on your machine, with your own broker API keys, and stores everything locally.

> **Status: early development.** Market data works end to end with Zerodha. Order placement is not available yet, and will be sandbox-only when it lands. See [Roadmap](#roadmap).

## What an agent can do today

| Tool | What it does |
| --- | --- |
| `get_broker_login_url` | Start a broker login. You log in on the broker's own page. |
| `connect_broker` | Finish the login; the session is stored encrypted and never returned. |
| `sync_instruments` | Download the broker's instrument list (~80,000 contracts) into a local database. |
| `search_instruments` | Find symbols: `RELIANCE`, `NIFTY 50`, all `NIFTY22SEP26` options, ... |
| `get_quote` | Live last traded price. |
| `get_historical_bars` | OHLCV candles (minute to daily), also stored locally in DuckDB. |
| `get_option_chain` | Calls and puts around at-the-money for an index or stock: price, open interest, implied volatility, Greeks. |
| `place_order` | Paper trade: fill a MARKET order in the local sandbox at the live price. Nothing reaches the broker. |
| `get_positions`, `get_funds`, `get_orderbook` | Sandbox positions with live P&L, virtual capital and margin, order history. |
| `evaluate_risk` | Check stop loss, target and capital cap settings against the live price before acting. |
| `get_audit_log` | What OpenTicker has done and who triggered it, most recent first. |

Example session, in plain language to your agent:

> "Connect Zerodha, then show me the last month of daily candles for RELIANCE and this week's NIFTY option chain with IV and delta."

## Quickstart

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and a [Zerodha Kite Connect](https://developers.kite.trade/) app.

```bash
git clone https://github.com/kushalBanda/openticker.git
cd openticker
uv sync
cp .env.example .env    # add KITE_API_KEY and KITE_API_SECRET
```

Setting up the Kite app, step by step: [docs/setup/zerodha.md](docs/setup/zerodha.md).

### Add it to your agent

**Claude Code**

```bash
claude mcp add openticker -- uv --directory /absolute/path/to/openticker run openticker-mcp
```

**Any MCP client** (JSON config)

```json
{
  "mcpServers": {
    "openticker": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/openticker", "run", "openticker-mcp"]
    }
  }
}
```

Then ask the agent to connect Zerodha. It walks you through login and instrument sync.

### Notifications (optional)

Orders and risk breaches can be sent to Slack (Incoming Webhook) and/or email (any SMTP server, including Resend and Amazon SES). Set the variables in `.env`; see `.env.example`. Everything is recorded in the local audit log either way.

## How it works

```
 MCP client (agent)
      │  tool calls over stdio
      ▼
 adapters/inbound/mcp_server.py      tool definitions, result models, agent-facing errors
      │
      ▼
 use_cases/                          one function per operation
      │                 │
      ▼                 ▼
 ports/ (Protocols) ◄── adapters/brokers/zerodha    Kite Connect: auth, instruments, market data
      │
 events/   bus: audit log (inline) · notifications to Slack/email (background)
 storage/  SQLite (credentials, instruments, audit log) · DuckDB (historical bars)
```

Hexagonal architecture: domain logic depends only on interfaces, so adding a broker or another entry point (REST, webhooks) doesn't touch the core. Every significant design decision is written up in [docs/adr/](docs/adr/).

Data lives in `~/.openticker` (override with `OPENTICKER_HOME`). Broker session tokens are encrypted at rest with a locally generated key.

## Roadmap

- An always-on server with a REST API mirroring the MCP tools
- Live prices and a market calendar
- Strategies that run unattended: multi-leg options strategies chosen relative to the market, strategy-wide stop loss, target, profit lock and kill switch, surviving restarts
- Signal strategies driven by ChartInk or TradingView alerts
- Hosting your own Python strategy scripts, without handing them your broker keys
- More brokers, added on demand

A web UI is planned after the agent-first surface is complete.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); new brokers are a great first area. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md), and report security issues privately as described in [SECURITY.md](SECURITY.md).

## Disclaimer

OpenTicker is not investment advice and is provided without warranty (see [LICENSE](LICENSE)). Trading involves risk of loss. You are responsible for every action taken with your broker account, including actions taken by an AI agent you connect to it.

OpenTicker is an independent project, not affiliated with or endorsed by Zerodha or any other broker. Your use of a broker's API is governed by that broker's terms.

## License

[MIT](LICENSE)
