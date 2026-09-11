---
name: run-backtest
description: Use when the user wants to backtest a trading strategy against real historical bars - e.g. "backtest a moving average crossover on Reliance", "run pairs trading on RELIANCE and TCS", "how would buy-and-hold have done on TCS this year". Not for a plain data fetch (use fetch-bars) or a written research report (use research).
---

# Run backtest

Runs one of the registered strategies (`packages/strategy`) against real historical bars via the `run_backtest` MCP tool (`quant-engine` server), and reports the resulting performance.

## Steps

1. If the user hasn't connected an adapter yet (or `run_backtest` raises a not-connected/session-expired error), invoke the connect-adapter skill yourself, then retry - do not just tell the user to run it themselves.
2. Read `plugin/references/strategies.md` to pick the right `strategy` name and work out its required `params` from what the user described. If the user named a strategy concept but not exact params (e.g. "a moving average crossover"), pick reasonable defaults from that reference and say what you picked - do not silently guess without telling the user.
3. Work out the symbol list and lookback window from what the user said, same day-count parsing as fetch-bars (e.g. "last year" -> `days=365`). `pairs_trading` and `time_series_momentum` need more than one symbol to be meaningful; ask the user for a symbol list if they only gave one.
4. Call `run_backtest(strategy=..., symbols=[...], params={...}, interval=..., days=..., cash=..., provider=None)`. Use tradingsymbols as the user gave them (e.g. `RELIANCE`, not `NSE:RELIANCE`).
5. If the tool raises an error (no session, expired session, rate-limited, no data, unknown strategy, bad params), relay that message plainly and suggest the concrete next step it names - do not show a raw stack trace.
6. If `performance` comes back `None` (bars too irregularly spaced to annualize), relay the `performance_note` plainly as a known data-completeness limitation, and still report `ending_equity`/positions (not just `ending_cash` - see step 7) - do not treat this as a failed run.
7. Otherwise, turn the `performance` report (total return, annualized return, max drawdown, Sharpe ratio, win rate) into a plain-language summary. State the actual numbers, not vague language like "it did well." This is a backtest result, not investment advice - do not give a buy/sell recommendation.
8. Always lead with `ending_equity` (cash plus the mark-to-market value of any open position), not `ending_cash` alone - a strategy that converts most cash into an open position (e.g. buy_and_hold) will show low `ending_cash` that reads as a loss even when the position's value makes the run profitable. Mention `ending_cash` and `positions` as supporting detail, but `ending_equity` is the number that answers "how did the strategy do."
