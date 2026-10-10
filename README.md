<h1><img src="assets/profile.png" alt="OpenTicker" width="360"></h1>

**A trading desk for Indian markets that you watch and your coding agent runs.**

OpenTicker runs on your machine with your own Zerodha keys. Claude Code, Codex, or any [MCP](https://modelcontextprotocol.io) client trades through it: quotes, option chains with Greeks, paper orders, strategies that run unattended, and reviews of what worked. A web app on the same server shows every move as it happens, says who made it, and lets you step in.

> **Status: early development.** Market data works end to end with Zerodha. Every order is a paper trade in a local sandbox that pays the real bid or ask and real Indian charges. Nothing is sent to the broker. See [Roadmap](#roadmap).

![The Dashboard: today's P&L after charges, the day's minute line, and what happened since your last visit](docs/images/web-dashboard.png)

## The web app

Open it and you see today: P&L after charges, the shape of the day, and what changed since you last looked. Everything after that is live over one WebSocket.

- **Every line says who did it.** You, Claude, Codex, a strategy, a TradingView alert, or one of your scripts. Agents show up by name.
- **Paper fills cost what real ones would.** A buy pays the ask, a sell gets the bid, and each fill keeps its brokerage, STT, fees, stamp duty and GST line by line.
- **Problems come to you.** A killed strategy or an expired Zerodha session sits at the top of the page with the button that fixes it. Fills and stops arrive as toasts.
- **You can step in without your agent.** Close a position, kill a strategy, or place a paper order from any page with ⌘K.

| | |
| --- | --- |
| ![Positions, marked live, with who holds each](docs/images/web-positions.png) | ![The option chain, live, with bids and asks to pick](docs/images/web-option-chain.png) |
| **Portfolio.** Positions, orders and trades, marked with every tick. Each position shows which strategies hold part of it. | **Option chain.** One expiry live with bids, asks and Greeks. Pick legs and see the payoff, margin with hedge benefit, and charges before you place the basket. |
| ![A strategy: its legs, equity after costs and latest review](docs/images/web-strategy.png) | ![An instrument: candles with your fills, and market depth](docs/images/web-symbol.png) |
| **Strategies.** Each one's state, legs marked live, equity curve after costs, alert URL, and its latest review's verdict. | **Instruments.** Candles with your fills marked, five levels of market depth, and today's orders for that symbol. |

The rest of the app covers named watchlists your agent can edit too, your own Python scripts with live logs and memory use, the agents that have connected with their calls today, a filterable activity log, and settings for the broker login, API keys and the paper account.

Light and dark follow your system. The app is for laptop and desktop screens, 1280 pixels wide and up.

### The Brain: what the desk learned

![The Brain: what the desk learned, as a graph of linked notes](docs/images/web-brain.png)

The Brain is a graph of linked notes about days, lessons, proposals, strategies, and symbols. It lives on your machine, and any agent can read it.

- **Daily debriefs.** After each close, your own Claude Code or Codex can write the day up: why each trade happened, what was given up, and what could have been done better.
- **Lessons earn their status.** A lesson starts as a hunch. Checks against later trades make it tested, then a rule, or retire it. One bad day stays a hunch.
- **Proposals wait for you.** An agent can propose one change to a strategy. Nothing changes until you accept it.
- **Reading is measured.** Agents search lessons before they design or review a strategy, and the page counts how often they do.

![A day's debrief: each trade with why and what was given up, and the lessons it checked](docs/images/web-brain-day.png)

## Built for coding agents

OpenTicker gives your agent 90 MCP tools and a place to work. You describe an idea in plain words. The agent turns it into a strategy, previews it against today's market, and runs it on paper.

> "Sell an ATM NIFTY straddle every weekday at 9:20 with a 30% stop on each leg. Show me what it would trade right now."

> "Make a signal strategy that buys 10 RELIANCE on my TradingView alert, with a 1% stop. Give me the alert URL."

> "Review my straddle's last 20 runs after costs. Keep it, change one thing, or retire it?"

- **Claude Code, Codex, or any MCP client.** One command adds it to Claude Code, and the JSON config works everywhere else.
- **A research folder, ready to go.** `labs/` sets up Claude Code and Codex with shared instructions and skills: `new-strategy`, `review-strategy`, and `debrief-day`.
- **Reviews and debriefs run unattended.** `openticker-serve` runs your own Claude Code or Codex as a background job, on demand or on a schedule. Each job gets a key that reads only what it needs: one strategy for a review, one day for a debrief.
- **Strategies don't need the conversation.** Once started or scheduled, the server enters, watches and exits them on their own stops, targets, and limits. Signal strategies take TradingView and ChartInk alerts at their own URL.
- **Your scripts too.** Upload a Python script and it runs under the server with a per-run API key, a clean environment, and memory and CPU limits. It never sees your broker keys.

<details>
<summary>All 90 tools, by area</summary>

| Area | Tools |
| --- | --- |
| Broker and data | `get_broker_login_url`, `connect_broker`, `sync_instruments`, `search_instruments`, `get_quote`, `get_quotes`, `get_market_depth`, `get_historical_bars`, `get_option_chain`, `get_market_status` |
| Paper trading | `place_order`, `place_basket`, `modify_order`, `cancel_order`, `cancel_all_orders`, `close_position`, `close_all_positions`, `get_positions`, `get_funds`, `get_orderbook`, `get_order_status`, `get_tradebook` |
| Costs and risk | `preview_charges`, `preview_paper_margin`, `preview_payoff`, `get_margin`, `check_charge_rates`, `get_charges_summary`, `get_pnl_history`, `evaluate_risk` |
| Options strategies | `create_strategy`, `update_strategy`, `get_strategy`, `list_strategies`, `delete_strategy`, `preview_strategy`, `start_strategy`, `stop_strategy`, `close_strategy_leg`, `schedule_strategy`, `unschedule_strategy`, `kill_strategy`, `release_kill_switch`, `get_strategy_runs`, `get_strategy_run`, `get_strategy_ledger` |
| Signal strategies | `create_signal_strategy`, `update_signal_strategy`, `rotate_strategy_webhook`, `disable_strategy_webhook`, `get_strategy_signals` |
| Scripts | `upload_script`, `update_script`, `delete_script`, `list_scripts`, `get_script`, `start_script`, `stop_script`, `schedule_script`, `unschedule_script`, `get_script_logs` |
| Agent jobs | `start_review`, `schedule_review`, `unschedule_review`, `get_agent_jobs`, `get_agent_job_log`, `stop_agent_job` |
| The Brain | `get_brain_graph`, `search_brain`, `get_brain_note`, `get_day_record`, `write_debrief`, `create_lesson`, `update_lesson`, `check_lesson`, `record_lesson_use`, `set_lesson_override`, `raise_proposal`, `decide_proposal`, `start_debrief`, `schedule_debrief`, `get_debrief_schedule`, `get_learning` |
| Watchlists | `list_watchlists`, `create_watchlist`, `add_to_watchlist`, `remove_from_watchlist`, `rename_watchlist`, `delete_watchlist` |
| Audit | `get_audit_log` |

</details>

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

### Start the web app

`openticker-serve` also serves a web app at `http://127.0.0.1:8750`. Build it once (needs [Node 22](https://nodejs.org) and [pnpm](https://pnpm.io)), then start the server:

```bash
cd ui && pnpm install && pnpm build && cd ..
uv run openticker-serve
```

It prints a sign-in link and opens it in your browser; `uv run openticker-serve ui login` prints another. The link works once, for 10 minutes, and signs that browser in for 30 days. The server listens on this machine only.

### Research with your agent: `labs/`

The repository ships a `labs/` folder set up for Claude Code and Codex: the OpenTicker server already configured, shared instructions, and skills such as `new-strategy`, which turns an idea in plain words into a paper strategy previewed against today's market.

```bash
uv run openticker-serve   # in its own terminal: watches strategies once they run
cd labs
claude                    # or: codex
```

Then describe an idea. Your notes go in `labs/notes/`, which is never committed. Once a strategy has run at least 10 times, ask the agent to review it: the `reviewer` judges its runs after costs against what your note said would prove it wrong, and writes a dated verdict (keep, change one thing, or retire) into the note. It can't change anything else. `openticker-serve` can also run that review unattended, when you ask (`start_review`) or on a schedule you set per strategy (`schedule_review`: every so often, after so many runs, or when it falls a set amount below its high), with your own Claude Code or Codex, signed in as you. A scheduled review waits for a new run to have ended, so an idle strategy costs nothing. The job reaches OpenTicker over MCP at `/mcp` on the server, with a key that reads only that strategy. See [labs/playbook](labs/playbook/README.md).

### REST API (optional)

Everything the tools do is also available over HTTP, for scripts and tools that aren't MCP clients:

```bash
uv run openticker-serve keys create laptop    # prints a key, once
uv run openticker-serve                       # http://127.0.0.1:8750, docs at /docs
curl -H "X-API-Key: otk_..." "http://127.0.0.1:8750/api/v1/quote?broker=zerodha&symbol=RELIANCE&exchange=NSE"
```

Every route except `/health` and signal strategies' alert URLs needs a key. An alert URL (`/webhooks/strategies/<token>`) carries its own token, which is shown once by `rotate_strategy_webhook`; to receive alerts from TradingView or ChartInk, put `openticker-serve` behind a tunnel or reverse proxy and set `OPENTICKER_PUBLIC_URL` to its address. `keys list` and `keys revoke <name>` manage them. The server listens on this machine only unless `OPENTICKER_BIND` says otherwise.

The server also streams live prices from the broker (Kite's WebSocket ticker) for every open sandbox position, every waiting order and anything listed in `OPENTICKER_WATCH`. It fills waiting LIMIT/SL/SL-M orders as prices cross them, closes intraday (MIS) positions 15 minutes before the session ends, and settles expired futures and options at the underlying's closing price on expiry day. If the broker session expires, it notifies you to log in again.

It also runs your uploaded Python scripts. Each gets `OPENTICKER_URL` and `OPENTICKER_API_KEY` in an environment that holds nothing else of yours, and calls the API like any client:

```python
import os, httpx

api = httpx.Client(base_url=os.environ["OPENTICKER_URL"],
                   headers={"X-API-Key": os.environ["OPENTICKER_API_KEY"]})
api.post("/api/v1/orders", json={"broker": "zerodha", "symbol": "SBIN", "exchange": "NSE",
                                 "side": "BUY", "quantity": 10, "product": "MIS"})
```

Scripts are your own trusted code: they run as your user and could read your files. The clean environment keeps secrets from reaching them by accident; it is not a sandbox for code from strangers (ADR 25).

### Notifications (optional)

Orders and risk breaches can be sent to Slack (Incoming Webhook) and/or email (any SMTP server, including Resend and Amazon SES). Set the variables in `.env`; see `.env.example`. Everything is recorded in the local audit log either way.

## How it works

```
 MCP client (agent)                  HTTP client · browser (ui/)
      │  tool calls over stdio          │  X-API-Key or session cookie; live prices over one WebSocket
      ▼                                 ▼
 adapters/inbound/mcp_server.py      adapters/inbound/rest_api.py, web/ (openticker-serve)
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

- More brokers, added on demand

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); new brokers are a great first area. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md), and report security issues privately as described in [SECURITY.md](SECURITY.md).

## Disclaimer

OpenTicker is not investment advice and is provided without warranty (see [LICENSE](LICENSE)). Trading involves risk of loss. You are responsible for every action taken with your broker account, including actions taken by an AI agent you connect to it.

OpenTicker is an independent project, not affiliated with or endorsed by Zerodha or any other broker. Your use of a broker's API is governed by that broker's terms.

## License

[Apache 2.0](LICENSE)
