# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Resting LIMIT, SL and SL-M sandbox orders (margin held while pending) filled by `openticker-serve` as live prices cross them; `cancel_order` tool and `DELETE /api/v1/orders/{order_id}`. Pending orders expire at the session's end. Intraday (MIS) positions are squared off 15 minutes before the close.
- Expiry settlement: positions in expired futures and options are closed at the underlying's closing price on expiry day (options at intrinsic value), including catch-up after the daemon was down. Notified as `PositionSettled`.
- Existing databases gain new columns automatically on upgrade (additive changes only, ADR 18).
- Market calendar with the 2026 NSE, BSE and MCX holidays, including MCX evening sessions and special sessions (`get_market_status` tool and route). Sandbox MARKET orders are refused while the exchange is closed.
- Live prices in `openticker-serve` from Kite's WebSocket ticker, for open sandbox positions and `OPENTICKER_WATCH`. Reconnects with backoff; an expired broker session sends one "log in" notification.
- REST API (`openticker-serve`) mirroring every MCP tool under `/api/v1`, with API keys (`openticker-serve keys create|list|revoke`) stored as hashes. Binds to `127.0.0.1:8750` by default (`OPENTICKER_BIND`).
- MCP server (`openticker-mcp`) with tools: `get_broker_login_url`, `connect_broker`, `sync_instruments`, `search_instruments`, `get_quote`, `get_historical_bars`.
- Zerodha (Kite Connect) broker adapter: login, instrument master, quotes, historical candles.
- Encrypted local storage of broker sessions (SQLite) and historical bars (DuckDB).
- Architecture decision records in `docs/adr/`.
- Event bus with an append-only audit log (`get_audit_log` tool) and notifications for orders and risk breaches via Slack Incoming Webhooks and SMTP email.
- Paper trading (`place_order`, `get_positions`, `get_funds`, `get_orderbook`): MARKET orders fill in a local sandbox at the broker's live price, with virtual capital, leverage-based margin, realized and unrealized P&L, an optional capital cap, and fill notifications. Nothing is sent to the broker.
- `evaluate_risk` tool: checks stop loss, target and capital cap settings against the live price.
- Option chains with implied volatility and Greeks (`get_option_chain`): Black-76 on the forward implied by the at-the-money pair, for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX and stock options.
- Strategy definitions (`create_strategy`, `update_strategy`, `get_strategy`, `list_strategies`, `delete_strategy`, `preview_strategy`, and `/api/v1/strategies`, ADR 20): options strategies of 1 to 10 legs chosen relative to the market (ATM or N strikes in or out of the money, weekly, next week, monthly or next month expiry, or a future), with a schedule and strategy-wide limits. A preview resolves the legs to real contracts at the live price. Strategies can't be started yet.
- Strategy-wide risk core (`core/risk/aggregate.py`, ADR 19): combined stop loss and target over a strategy's legs, profit lock and lock-and-trail, stops to entry when a leg's stop fires, and a daily loss limit. Not wired to anything yet.
- Risk core: per-position stop loss, target, continuous and stepped trailing stops, capital cap, and configuration validation (`core/risk`).
