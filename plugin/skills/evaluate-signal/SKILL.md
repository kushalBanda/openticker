---
name: evaluate-signal
description: Use when the user wants to know whether a signal (e.g. RSI, SMA) actually predicts forward returns for a symbol - e.g. "does RSI predict Reliance's next-week return", "check if this signal has any edge on TCS", "evaluate the momentum signal".
---

# Evaluate signal

Measures whether a registered signal's value is correlated with forward returns, via the `evaluate_signal` MCP tool (`quant-engine` server). Wraps `packages/quant/evaluation`'s Spearman information-coefficient evaluator.

Requires a connected provider first - if no session is stored, invoke the connect-adapter skill yourself before proceeding, rather than telling the user to run it.

## Steps

1. Identify the signal name (e.g. "rsi", "sma"), its constructor params (e.g. `{"period": 14}`), the symbol, and the forward-return horizon (in bars) from the user's request. If the user doesn't give a horizon, ask - do not silently default.
2. Work out `min_lookback` for the chosen signal - the smallest bar window `compute()` needs (for RSI, `period + 1`; for SMA, `window`). This is not inferred automatically - get it wrong and the tool's results will be misleading, not just wrong.
3. Call `evaluate_signal(signal=..., symbol=..., horizon=..., min_lookback=..., params={...}, provider=None)`.
4. If the tool raises a not-connected or session-expired error, invoke the connect-adapter skill yourself, then retry the `evaluate_signal` call - do not just tell the user to run it themselves.
5. If the tool raises an insufficient-data error, tell the user plainly - report a longer `days` window as the way to get more sample, not any change to the signal.
6. If the tool raises a rate-limited error, tell the user the provider throttled the request and offer to retry after a short wait - do not retry automatically in a loop.
7. If the tool raises a bad-params error, re-check the signal's constructor args (see step 1/2) and retry with corrected params rather than asking the user to debug it themselves.
8. Present the result: `information_coefficient` and `ic_p_value` (the raw read), but foreground `effective_ic_p_value` and the `overlapping_windows_caveat` text so the user doesn't over-trust the raw p-value on overlapping windows. Include `turnover_proxy` and both sample sizes.
