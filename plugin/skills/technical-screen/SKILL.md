---
name: technical-screen
description: Use when checking one symbol's chart against any technical indicator - trend (SMA, EMA, WMA, MACD, ADX, Parabolic SAR), momentum (RSI, Stochastic, Stochastic RSI, Williams %R, ROC, CCI), volatility (Bollinger Bands, ATR, realized volatility), volume (above-average volume, OBV, VWAP, Accumulation/Distribution), structure (breakout, support/resistance, candlestick pattern, gap, 52-week range position, pivot points), or cross-sectional (relative strength, correlation, beta, pairs spread) - e.g. "what's the RSI and 200-EMA on RELIANCE?", or as a step inside a scan-market run.
---

# Technical screen

Runs `plugin/skills/technical-screen/scripts/technical_screen.py`, an
open dispatch over every indicator in `plugin/lib/math/indicators/`. You
choose which indicators to ask for and with what parameters - this
script has no fixed report. See `plugin/references/scan-market.md` for
every indicator's formula and what it's typically used for.

## Steps

1. If the user hasn't connected an adapter yet (or the script's JSON
   output names a not-connected/session-expired problem), invoke the
   connect-adapter skill yourself, then retry.
2. Decide which indicators actually answer the question being asked.
   Don't request every indicator by default - pick the ones relevant to
   the setup you're evaluating (a momentum question wants RSI/stochastic,
   a trend question wants EMA/ADX, a pattern question wants
   candlestick_pattern/breakout).
3. Run `uv run python plugin/skills/technical-screen/scripts/technical_screen.py --symbol <symbol> --indicators <comma-separated names> [--params '<JSON overrides>'] [--benchmark-symbol <symbol>] [--days <days>] [--provider <provider>]`.
   `relative_strength`, `correlation`, `beta`, and `pairs_spread` need
   `--benchmark-symbol` (or a second symbol for a pairs check) - without
   it they report their own error, the rest of the request still runs.
   Widen `--days` past the default 400 for indicators needing more
   history (`fifty_two_week_range_position`'s default 252-bar lookback,
   or a long `beta`/`correlation` period).
4. Read each indicator's `"value"` and `"params_used"` - the latter tells
   you exactly which period/threshold was actually applied, including
   any default you didn't override. If an indicator reports `"error"`
   instead (not enough bars, unknown name, missing benchmark), the rest
   of the request still succeeded - only that one failed.
5. Weigh the readings yourself. Different indicator categories agreeing
   is more convincing than any single one; a strong trend reading
   alongside a contradicting momentum reading is a real conflict worth
   naming, not something to average away.
