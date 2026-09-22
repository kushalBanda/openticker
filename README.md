# OpenTicker

**A self-hosted trading platform for Indian markets that AI agents operate directly.**

OpenTicker exposes brokerage operations as [MCP](https://modelcontextprotocol.io) tools. Claude Code, Codex, or any MCP client can connect your broker, find instruments, and pull live quotes and historical candles by calling tools, with no UI in between. It runs on your machine, with your own broker API keys, and stores everything locally.

> **Status: early development.** Market data works end to end with Zerodha. Orders are paper trades in a local sandbox; nothing is sent to the broker. See [Roadmap](#roadmap).

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
| `place_order` | Paper trade in the local sandbox while the exchange is open: MARKET fills at the live price; LIMIT, SL and SL-M orders wait and fill when the price reaches them. Nothing reaches the broker. |
| `cancel_order` | Withdraw a waiting order. |
| `get_market_status` | Whether NSE, BSE, NFO, BFO and MCX are open now, and the next session. Knows weekends, exchange holidays and special sessions. |
| `get_positions`, `get_funds`, `get_orderbook` | Sandbox positions with live P&L, virtual capital and margin, order history. |
| `evaluate_risk` | Check stop loss, target and capital cap settings against the live price before acting. |
| `get_audit_log` | What OpenTicker has done and who triggered it, most recent first. |
| `create_strategy`, `update_strategy`, `get_strategy`, `list_strategies`, `delete_strategy` | Save options strategies of up to 10 legs chosen relative to the market (ATM, N strikes in or out of the money, weekly or monthly expiry), with a schedule and strategy-wide limits. |
| `preview_strategy` | The real contracts a strategy would trade right now, with prices and net premium. Places nothing. |

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

### REST API (optional)

Everything the tools do is also available over HTTP, for scripts and tools that aren't MCP clients:

```bash
uv run openticker-serve keys create laptop    # prints a key, once
uv run openticker-serve                       # http://127.0.0.1:8750, docs at /docs
curl -H "X-API-Key: otk_..." "http://127.0.0.1:8750/api/v1/quote?broker=zerodha&symbol=RELIANCE&exchange=NSE"
```

Every route except `/health` needs a key. `keys list` and `keys revoke <name>` manage them. The server listens on this machine only unless `OPENTICKER_BIND` says otherwise.

The server also streams live prices from the broker (Kite's WebSocket ticker) for every open sandbox position, every waiting order and anything listed in `OPENTICKER_WATCH`. It fills waiting LIMIT/SL/SL-M orders as prices cross them, closes intraday (MIS) positions 15 minutes before the session ends, and settles expired futures and options at the underlying's closing price on expiry day. If the broker session expires, it notifies you to log in again.

### Notifications (optional)

Orders and risk breaches can be sent to Slack (Incoming Webhook) and/or email (any SMTP server, including Resend and Amazon SES). Set the variables in `.env`; see `.env.example`. Everything is recorded in the local audit log either way.

## How it works

```
 MCP client (agent)                  HTTP client
      │  tool calls over stdio          │  X-API-Key
      ▼                                 ▼
 adapters/inbound/mcp_server.py      adapters/inbound/rest_api.py (openticker-serve)
      │                                 │
      └──────────────┬──────────────────┘
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
