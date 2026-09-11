---
name: research
description: Use when the user wants analysis or a research report on a symbol - trend, volatility, notable levels, optionally with news/fundamentals context - not just raw numbers. For a plain data fetch with no analysis, use the fetch-bars skill instead.
allowed-tools: Task
---

# Research

Produces a plain-language research report for a symbol, built from real OHLCV bars through the connected adapter, optionally enriched with outside context. No server call is involved.

## Steps

1. If no adapter is connected yet (or `fetch_bars` raises a not-connected/session-expired error), invoke the connect-adapter skill yourself, then continue - do not just tell the user to run it themselves.
2. Work out the lookback window from what the user said (default 365 days if unclear), same as the fetch-bars skill.
3. Call `fetch_bars(symbol=..., days=..., provider=None)` (the `quant-engine` MCP tool) to get real OHLCV bars.
4. If the tool raises an error (no session, expired session, no data for the symbol), relay that message plainly and stop - do not invoke the research-agent on missing data.
5. Otherwise, hand the tool's full result (the summary fields and the per-bar OHLCV list) to the `research-agent` subagent, and ask it to write the report. Let it use a web search / Exa tool for outside context if one is available - do not do that lookup yourself first.
6. Return the subagent's report to the user as the answer - do not also re-paste the raw OHLCV table on top of it unless the user specifically asks for the raw numbers.
