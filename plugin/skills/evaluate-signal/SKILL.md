---
name: evaluate-signal
description: Use when the user wants to know whether a signal (e.g. RSI, SMA) actually predicts forward returns for a symbol - e.g. "does RSI predict Reliance's next-week return", "check if this signal has any edge on TCS", "evaluate the momentum signal".
---

# Evaluate signal

Measures whether a signal's value is correlated with forward returns, by running `plugin/skills/evaluate-signal/scripts/evaluate_signal.py`. Wraps `plugin/lib/math/evaluation.py`'s Spearman information-coefficient evaluator.

Requires a connected provider first - if no session is stored, invoke the connect-adapter skill yourself before proceeding, rather than telling the user to run it.

## Steps

1. Identify the signal name (one of `rsi`, `sma`, `above_average_volume`, `time_series_momentum`), its params (e.g. `{"period": 14}` for rsi, `{"window": 14}` for the others), the symbol, and the forward-return horizon (in bars) from the user's request. If the user doesn't give a horizon, ask - do not silently default.
2. Work out `--min-lookback` for the chosen signal - the smallest bar window its compute function needs (for `rsi`, `period + 1`; for the others, `window`). This is not inferred automatically - get it wrong and the results will be misleading, not just wrong.
3. Run `uv run python plugin/skills/evaluate-signal/scripts/evaluate_signal.py --signal <name> --symbol <symbol> --horizon <n> --min-lookback <n> --params '<json>'`.
4. Parse the JSON stdout. If it has an `"error"` key naming a not-connected or session-expired problem, invoke the connect-adapter skill yourself, then retry the script call - do not just tell the user to run it themselves.
5. If the JSON's `"error"` names an insufficient-data problem, tell the user plainly - report a longer `--days` window as the way to get more sample, not any change to the signal.
6. If the JSON's `"error"` names a rate-limited problem, tell the user the provider throttled the request and offer to retry after a short wait - do not retry automatically in a loop.
7. If the JSON's `"error"` names a bad-params problem, re-check the signal's params (see step 1/2) and retry with corrected params rather than asking the user to debug it themselves.
8. Present the result: `information_coefficient` and `ic_p_value` (the raw read), but foreground `effective_ic_p_value` and the `overlapping_windows_caveat` text so the user doesn't over-trust the raw p-value on overlapping windows. Include `turnover_proxy` and both sample sizes.
