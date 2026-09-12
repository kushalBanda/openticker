---
name: fetch-bars
description: Use when the user asks for historical price/market data for a symbol - e.g. "fetch me Reliance data for the last year", "get AAPL prices", "show me the last 6 months of bars for TCS".
---

# Fetch bars

Fetches historical OHLCV bars for one symbol by running `plugin/skills/fetch-bars/scripts/fetch_bars.py`. This is the data-only slice - no written report, no web/news enrichment (that's the fuller research skill).

## Steps

1. If the user hasn't connected an adapter yet (or the script's JSON output has an `"error"` key naming a not-connected/session-expired problem), invoke the connect-adapter skill yourself, then retry - do not just tell the user to run it themselves.
2. Work out the lookback window from what the user said (e.g. "last year" -> `--days 365`, "last 6 months" -> `--days 180`, "last month" -> `--days 30`). Default to 365 if unclear.
3. Run `uv run python plugin/skills/fetch-bars/scripts/fetch_bars.py --symbol <symbol> --interval <interval> --days <days> [--provider <provider>]` with the user's tradingsymbol as they gave it (e.g. `RELIANCE`, not `NSE:RELIANCE`). Leave `--provider` unset unless the user names one explicitly - it falls back to whichever provider connected most recently.
4. Parse the script's JSON stdout. It carries full OHLCV - open, high, low, close, volume - for every bar, not just closes, plus a summary (`bar_count`, `first_close`, `last_close`). Turn this into a plain-language summary (date range, bar count, first/last close, min/max, percent change), and if the user asks about a specific date or wants the raw numbers, pull the exact OHLCV row from the `bars` list rather than approximating. Do not dump the raw bar list wholesale for a large range, but do not omit real OHLCV values either when the user actually wants them.
5. If the JSON has an `"error"` key (no session, expired session, rate-limited, no data for the symbol), relay that message plainly and suggest the concrete next step it names (reconnect, wait and retry, try a different symbol/range) - do not show a raw stack trace.
