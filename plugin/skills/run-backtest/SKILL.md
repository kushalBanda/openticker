---
name: run-backtest
description: Use when the user wants to backtest a trading strategy against real historical bars - e.g. "backtest a moving average crossover on Reliance", "run pairs trading on RELIANCE and TCS", "how would buy-and-hold have done on TCS this year". Not for a plain data fetch (use fetch-bars) or a written research report (use research).
allowed-tools: Bash, Read
---

# Run backtest

Runs one of the registered strategies (`packages/strategy`) against real historical bars fetched through whichever adapter the user has connected, and reports the resulting performance. No server call is involved - this runs the hand-built backtest engine directly, in-process.

## Steps

1. If the user hasn't connected an adapter yet, tell them to run the connect-adapter skill first - do not attempt this skill without a stored session.
2. Read `plugin/references/strategies.md` to pick the right `--strategy` name and work out its required `--param key=value` flags from what the user described. If the user named a strategy concept but not exact params (e.g. "a moving average crossover"), pick reasonable defaults from that reference and say what you picked - do not silently guess without telling the user.
3. Work out the symbol list and lookback window from what the user said, same day-count parsing as fetch-bars (e.g. "last year" -> `--days 365`). `pairs_trading` and `time_series_momentum` need more than one symbol to be meaningful; ask the user for a symbol list if they only gave one.
4. Run:
   ```
   uv run python plugin/scripts/run_backtest.py --strategy NAME --symbols A,B,C --days N --param key=value [--param key2=value2 ...]
   ```
   from the repo root. Use tradingsymbols as the user gave them (e.g. `RELIANCE`, not `NSE:RELIANCE`).
5. If the script exits with an error (no session, expired session, no data, unknown strategy, bad param), relay that message plainly and suggest the concrete next step it names - do not show a raw stack trace.
6. If the script reports "performance metrics unavailable" (bars too irregularly spaced to annualize), relay that plainly as a known data-completeness limitation, and still report the raw equity change and ending positions it prints - do not treat this as a failed run.
7. Otherwise, turn the printed report (total return, annualized return, max drawdown, Sharpe ratio, win rate, ending cash/positions) into a plain-language summary. State the actual numbers, not vague language like "it did well." This is a backtest result, not investment advice - do not give a buy/sell recommendation.
