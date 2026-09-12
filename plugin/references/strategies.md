# Strategies reference

All 5 strategies live in `plugin/lib/math/strategies/`, dispatched by name in `plugin/skills/run-backtest/scripts/run_backtest.py`'s `_STRATEGY_FACTORY` dict - no registry, plain lookup. Pass params as a JSON object: `--params '{"key": value, ...}'`.

**No-lookahead rule (applies to every strategy below):** orders placed on bar `i` fill on bar `i+1`'s open, never same-bar. This is load-bearing - it is what makes a backtest's result meaningful rather than an artifact of seeing the future.

## sma_cross

Faber (2007) single-moving-average timing rule: long while price is above its trailing SMA, flat (cash) when below. No short leg - Faber's own rule and its evidence (a 10-month SMA on the Dow since 1900, higher Sharpe and lower drawdown than buy-and-hold) only ever go long-or-flat.

- `long_window` (int, required) - SMA lookback in bars, e.g. `20`.
- Sizing - give exactly one of:
  - `quantity` (int) - fixed share count every entry.
  - `target_risk_pct` (float) + `vol_window` (int) - volatility-targeted sizing instead of a fixed count.

Example: `--params '{"long_window": 20, "quantity": 10}'`

## buy_and_hold

Buys `quantity` shares of every symbol on the first bar it sees that symbol, never trades again. The standard performance baseline (event-driven-backtester style) to compare an active strategy's return against no signal, no exit, no re-entry.

- `quantity` (int, required) - shares to buy per symbol.

Example: `--params '{"quantity": 10}'`

## mean_reversion

Bollinger Band mean reversion with RSI confirmation, ported from nautilus_trader's `BBMeanReversion`. Entry: price closes outside a band with RSI confirming the extreme (oversold -> long, overbought -> short), flipping straight through any opposite position. Exit: price reverts to the middle band, checked before entry every bar.

- `bb_window` (int, required) - Bollinger Band lookback.
- `bb_std` (float, required) - Bollinger Band width in standard deviations, e.g. `2.0`.
- `rsi_period` (int, required) - RSI lookback.
- `rsi_buy_threshold` (float, required) - RSI level below which oversold entry is confirmed, e.g. `30`.
- `rsi_sell_threshold` (float, required) - RSI level above which overbought entry is confirmed, e.g. `70`.
- `quantity` (int, required) - fixed share count per entry.

Example: `--params '{"bb_window": 20, "bb_std": 2.0, "rsi_period": 14, "rsi_buy_threshold": 30, "rsi_sell_threshold": 70, "quantity": 10}'`

## pairs_trading

Gatev, Goetzmann & Rouwenhorst pairs trading. Every `trading_months`, force-unwinds any open pair positions, re-ranks every symbol pair in the universe by sum-of-squared-deviation over the trailing `formation_months`, and freezes each kept pair's spread mean/std over that window. During the trading window, each selected pair's live spread is z-scored against its frozen baseline (never re-anchored mid-period): flat and `|z| > entry_z` opens the pair (short the rich leg, long the cheap leg); open and the z-score's sign has flipped since entry closes both legs. **Needs multiple symbols** (a real pair universe, not one symbol) to do anything.

- `formation_months` (int, required) - lookback window (months) used to rank pairs and freeze each pair's spread baseline.
- `trading_months` (int, required) - how long a formation is traded before the next re-ranking.
- `top_n_pairs` (int, required) - how many top-ranked pairs to actually trade, splitting `cash / top_n_pairs` equal-weight across each.
- `entry_z` (float, required) - z-score threshold that opens a pair position, e.g. `2.0`.

Example: `--symbols RELIANCE TCS INFY WIPRO --params '{"formation_months": 12, "trading_months": 3, "top_n_pairs": 2, "entry_z": 2.0}'`

## time_series_momentum

Moskowitz, Ooi & Pedersen (2012) time-series momentum, single instrument: long when the instrument's own trailing-window return is positive, short when negative, flat when exactly zero. Volatility-targeted sizing is not an optional add-on here, it is the sizing rule the strategy is defined by. Rebalances monthly, not every bar. Single-instrument caveat: the paper's documented Sharpe is for a diversified 58-instrument portfolio, not one symbol - judge a single-instrument backtest's result on its own merits, not against that benchmark.

- `window` (int, required) - trailing-return lookback in bars, e.g. `252` for a 12-month return on daily bars.
- `target_risk_pct` (float, required) - fraction of account equity targeted as risk per position.
- `vol_window` (int, required) - lookback for the realized-volatility estimate used to scale position size.

Example: `--params '{"window": 252, "target_risk_pct": 0.02, "vol_window": 20}'`

## Notes

- `run_backtest.py --cash N` sets starting cash, default 100,000.
- If the fetched bars are too irregularly spaced to compute an annualized Sharpe/return, the script reports `performance: null` with a `performance_note` explaining why, rather than failing outright.
- No paper/live trading exists in this workspace, this is backtest-only. If it is wanted later, it gets designed fresh against the flat `plugin/lib/math` shape.
- `plugin/lib/math/portfolio.py`'s `Portfolio.apply_fills` uses one unified signed-delta formula (buy = +quantity, sell = -quantity) for realized P&L, not separate long/short branches, including the flip-through-zero case (see `docs/superpowers/specs/2026-09-03-trade-ledger-design.md` for the full derivation).
