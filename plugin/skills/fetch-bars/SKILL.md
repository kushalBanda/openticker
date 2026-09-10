---
name: fetch-bars
description: Use when the user asks for historical price/market data for a symbol - e.g. "fetch me Reliance data for the last year", "get AAPL prices", "show me the last 6 months of bars for TCS".
allowed-tools: Bash
---

# Fetch bars

Fetches historical bars for a symbol through whichever adapter the user has connected (see the connect-adapter skill), and reports a plain-language summary. This is the data-only slice - no written report, no web/news enrichment (that's the fuller research skill, not yet built).

## Steps

1. If the user hasn't connected an adapter yet, tell them to run the connect-adapter skill first - do not attempt this skill without a stored session.
2. Work out the lookback window from what the user said (e.g. "last year" -> `--days 365`, "last 6 months" -> `--days 180`, "last month" -> `--days 30`). Default to 365 if unclear.
3. Run:
   ```
   uv run python plugin/scripts/fetch_bars.py SYMBOL --days N
   ```
   from the repo root, with the user's symbol and the resolved day count. Use the tradingsymbol as they gave it (e.g. `RELIANCE`, not `NSE:RELIANCE`).
4. The script prints full OHLCV - open, high, low, close, volume - for every bar, not just closes. Turn this into a plain-language summary (date range, bar count, first/last close, min/max, percent change), and if the user asks about a specific date or wants the raw numbers, pull the exact OHLCV row from the script's output rather than approximating. Do not just paste the raw script output wholesale for a large range, but do not omit real OHLCV values either when the user actually wants them.
5. If the script exits with an error (no session, expired session, no data for the symbol), relay that message plainly and suggest the concrete next step it names (reconnect, try a different symbol/range) - do not show a raw stack trace.
