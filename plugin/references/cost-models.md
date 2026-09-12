# Broker cost models reference

Real Kite (Zerodha) and Groww equity charge schedules, implemented as flat functions in `plugin/lib/math/cost_models.py`, verified against zerodha.com/charges and groww.in/pricing (fetched 2026-09-12).

**Approximation, disclosed:** STT and exchange/SEBI charges are applied on every fill even though the real schedules charge some components on one side only (STT sell-only for intraday, stamp duty buy-only, DP charge sell-only for Groww). This is a same-rate-both-sides approximation - the error is small next to the dominant STT/brokerage terms. GST (18% on brokerage + exchange + SEBI charges) is folded into the delivery presets exactly (Kite's delivery brokerage is always Rs 0, so GST's base there is fixed) and left out of the intraday presets as a disclosed small under-estimate (brokerage there is a variable capped amount).

## kite_delivery_cost(quantity, price)

Zerodha equity delivery: Rs 0 brokerage, but STT/exchange/SEBI/stamp-duty/GST still apply on every fill.

| Charge | Rate |
|---|---|
| STT | 10.0 bps (0.1%), both sides |
| Exchange transaction charge | 0.307 bps |
| SEBI charge | 0.01 bps |
| Stamp duty | 1.5 bps (buy side only in reality, approximated both) |
| GST | 18% of (exchange + SEBI charges) |

## kite_intraday_cost(quantity, price)

Zerodha equity intraday: brokerage capped at `min(0.03% of notional, Rs 20/order)`, plus STT/exchange/SEBI/stamp-duty.

| Charge | Rate |
|---|---|
| Brokerage | min(3.0 bps, Rs 20/order) |
| STT | 2.5 bps (sell side only in reality, approximated both) |
| Exchange transaction charge | 0.307 bps |
| SEBI charge | 0.01 bps |
| Stamp duty | 0.3 bps (buy side only in reality, approximated both) |

## groww_delivery_cost(quantity, price)

Groww equity delivery: brokerage capped at `min(0.1% of notional, Rs 20/order)` since Groww's mid-2024 pricing change (no longer free), plus STT/exchange/SEBI/stamp-duty and a flat Rs 16.5 DP charge.

| Charge | Rate |
|---|---|
| Brokerage | min(10.0 bps, Rs 20/order) |
| STT | 10.0 bps, both sides |
| Exchange transaction charge | 0.297 bps |
| SEBI charge | 0.01 bps |
| Stamp duty | 1.5 bps (buy side only in reality, approximated both) |
| DP charge | flat Rs 16.5 (sell side only in reality, approximated every fill) |

## groww_intraday_cost(quantity, price)

Groww equity intraday: brokerage capped at `min(0.1% of notional, Rs 20/order)`, plus STT/exchange/SEBI/stamp-duty. No DP charge (that only applies to a delivery sell).

| Charge | Rate |
|---|---|
| Brokerage | min(10.0 bps, Rs 20/order) |
| STT | 2.5 bps (sell side only in reality, approximated both) |
| Exchange transaction charge | 0.297 bps |
| SEBI charge | 0.01 bps |
| Stamp duty | 0.3 bps (buy side only in reality, approximated both) |

## slippage_fill_price(price, side, bps)

Shifts the fill price against the trader by `bps` basis points: a buy pays a worse (higher) price, a sell receives a worse (lower) price. `bps=0.0` (the default cost profile) returns `price` unchanged. Applied separately from the cost functions above - these model brokerage/statutory charges, not market impact.
