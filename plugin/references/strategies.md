# Strategies reference

Every strategy registered in `packages/strategy` (`strategy.core.registry.list_strategy_names()`), for the run-backtest skill to pick a `--strategy` name and `--param key=value` flags from. Params are plain int/float constructor arguments - `run_backtest.py` casts each `--param` value to int first, then float.

## sma_cross

Faber (2007) single-moving-average timing rule: long while price is above its trailing SMA, flat (cash) when below. No short leg.

- `long_window` (int, required) - SMA lookback in bars, e.g. `20`.
- Sizing - give exactly one of:
  - `quantity` (int) - fixed share count every entry.
  - `target_risk_pct` (float) + `vol_window` (int) - volatility-targeted sizing instead of a fixed count.

Example: `--param long_window=20 --param quantity=10`

## buy_and_hold

Buys `quantity` shares of every symbol on the first bar it sees that symbol, never trades again. The standard baseline to compare an active strategy against.

- `quantity` (int, required) - shares to buy per symbol.

Example: `--param quantity=10`

## mean_reversion

Bollinger Band mean reversion with RSI confirmation (ported from nautilus_trader's `BBMeanReversion`). Entry: price closes outside a band with RSI confirming the extreme (oversold -> long, overbought -> short). Exit: price reverts to the middle band.

- `bb_window` (int, required) - Bollinger Band lookback.
- `bb_std` (float, required) - Bollinger Band width in standard deviations, e.g. `2.0`.
- `rsi_period` (int, required) - RSI lookback.
- `rsi_buy_threshold` (float, required) - RSI level below which oversold entry is confirmed, e.g. `30`.
- `rsi_sell_threshold` (float, required) - RSI level above which overbought entry is confirmed, e.g. `70`.
- `quantity` (int, required) - fixed share count per entry.

Example: `--param bb_window=20 --param bb_std=2.0 --param rsi_period=14 --param rsi_buy_threshold=30 --param rsi_sell_threshold=70 --param quantity=10`

## pairs_trading

Gatev, Goetzmann & Rouwenhorst pairs trading. Every `trading_months`, re-ranks every symbol pair in the universe by formation-window spread deviation, trades the top-ranked pairs' z-scored spread. **Needs multiple symbols** (a real pair universe, not one symbol) to do anything.

- `formation_months` (int, required) - lookback window (months) used to rank pairs and freeze each pair's spread baseline.
- `trading_months` (int, required) - how long a formation is traded before the next re-ranking.
- `top_n_pairs` (int, required) - how many top-ranked pairs to actually trade.
- `entry_z` (float, required) - z-score threshold that opens a pair position, e.g. `2.0`.

Example: `--symbols RELIANCE,TCS,INFY,WIPRO --param formation_months=12 --param trading_months=3 --param top_n_pairs=2 --param entry_z=2.0`

## time_series_momentum

Moskowitz, Ooi & Pedersen (2012) time-series momentum, single instrument: long when the instrument's own trailing-window return is positive, short when negative. Volatility-targeted sizing is not optional here, it is the strategy's defining sizing rule. Rebalances monthly, not every bar. Single-instrument caveat: the paper's documented Sharpe is for a diversified 58-instrument portfolio, not one symbol - judge results on their own, not against that benchmark.

- `window` (int, required) - trailing-return lookback in bars, e.g. `252` for a 12-month return on daily bars.
- `target_risk_pct` (float, required) - fraction of account equity targeted as risk per position.
- `vol_window` (int, required) - lookback for the realized-volatility estimate used to scale position size.

Example: `--param window=252 --param target_risk_pct=0.02 --param vol_window=20`

## Notes

- `run_backtest.py --cash N` sets starting cash, default 100,000.
- If the fetched bars are too irregularly spaced to compute an annualized Sharpe/return (a known `packages/ingest` data-completeness gap), the script reports raw (non-annualized) equity change instead of failing outright.
- No paper/live trading exists in this workspace - `packages/execution` was deprecated and removed (see root `CLAUDE.md`). This is backtest-only.
