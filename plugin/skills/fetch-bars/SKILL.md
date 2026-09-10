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
4. Turn the script's output into a plain-language summary: date range, how many bars, first/last close, min/max, and the percent change over the range. Do not just paste the raw script output.
5. If the script exits with an error (no session, expired session, no data for the symbol), relay that message plainly and suggest the concrete next step it names (reconnect, try a different symbol/range) - do not show a raw stack trace.
