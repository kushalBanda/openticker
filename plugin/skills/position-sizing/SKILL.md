---
name: position-sizing
description: Use when the user wants a suggested stop-loss, take-profit, and position size for a trade - e.g. "size a trade on RELIANCE with 2 lakh capital at 1% risk", or as a step inside a scan-market run.
---

# Position sizing

Runs `plugin/skills/position-sizing/scripts/position_sizing.py`, which
suggests a stop-loss, take-profit, and quantity for one symbol from its
recent bars, the user's capital, and a risk-per-trade percentage. This
script suggests numbers - you decide whether to use them as-is or adjust
them given the rest of what you know about the setup.

## Steps

1. If the user hasn't connected an adapter yet, invoke the
   connect-adapter skill yourself, then retry.
2. If the user hasn't given capital and a risk-per-trade percentage in
   this conversation, ask for both before running the script. Never
   assume a default risk percentage for real money sizing.
3. Run `uv run python plugin/skills/position-sizing/scripts/position_sizing.py --symbol <symbol> --capital <capital> --risk-pct <risk_per_trade_pct> [--reward-risk-ratio <ratio>] [--provider <provider>]`.
4. Read the JSON: `entry_price`, `stop_distance`, `stop_price`,
   `take_profit`, `quantity`. State all four plainly. If your own read
   of the setup calls for a tighter or wider stop than the script's
   structural-low suggestion, say so and adjust - this number is a
   starting point, not a rule.
5. If the JSON has an `"error"` key, relay it plainly.
