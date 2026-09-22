# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- MCP server (`openticker-mcp`) with tools: `get_broker_login_url`, `connect_broker`, `sync_instruments`, `search_instruments`, `get_quote`, `get_historical_bars`.
- Zerodha (Kite Connect) broker adapter: login, instrument master, quotes, historical candles.
- Encrypted local storage of broker sessions (SQLite) and historical bars (DuckDB).
- Architecture decision records in `docs/adr/`.
- Event bus with an append-only audit log (`get_audit_log` tool) and notifications for orders and risk breaches via Slack Incoming Webhooks and SMTP email.
- Paper trading (`place_order`, `get_positions`, `get_funds`, `get_orderbook`): MARKET orders fill in a local sandbox at the broker's live price, with virtual capital, leverage-based margin, realized and unrealized P&L, an optional capital cap, and fill notifications. Nothing is sent to the broker.
- `evaluate_risk` tool: checks stop loss, target and capital cap settings against the live price.
- Option chains with implied volatility and Greeks (`get_option_chain`): Black-76 on the forward implied by the at-the-money pair, for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX and stock options.
- Risk core: per-position stop loss, target, continuous and stepped trailing stops, capital cap, and configuration validation (`core/risk`).
