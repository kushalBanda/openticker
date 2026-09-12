"""Real Kite (Zerodha) and Groww equity charge schedules, verified against
zerodha.com/charges and groww.in/pricing (fetched 2026-09-12).

Ported from strategy.core.cost_model, flattened: the TransactionCostModel/
SlippageModel Protocols and the PerShareFeeModel/FlatFeeModel/
PercentOfNotionalModel/AggregateCostModel combinator classes are dropped.
Each preset is now one straight line function inlining the same bps
arithmetic those classes used to compose.

STT and exchange/SEBI charges are applied on every fill even though the
real schedules charge some components on one side only (STT sell-only for
intraday, stamp duty buy-only, DP charge sell-only for Groww), a
same-rate-both-sides approximation, disclosed here rather than modeled
exactly, since the error is small next to the dominant STT/brokerage
terms. GST (18% on brokerage + exchange + SEBI charges) is folded into
the delivery presets exactly (Kite's delivery brokerage is always Rs 0,
so GST's base there is fixed) and left out of the intraday presets as a
disclosed small under-estimate (brokerage there is a variable capped
amount).
"""

from typing import Final

_KITE_STT_DELIVERY_BPS: Final = 10.0  # 0.1%, both sides
_KITE_STT_INTRADAY_BPS: Final = 2.5  # 0.025%, sell side only (approximated: both)
_KITE_EXCHANGE_TXN_BPS: Final = 0.307  # 0.00307%, both sides
_KITE_SEBI_BPS: Final = 0.01  # 0.0001%, both sides
_KITE_STAMP_DUTY_DELIVERY_BPS: Final = 1.5  # 0.015%, buy side only (approximated: both)
_KITE_STAMP_DUTY_INTRADAY_BPS: Final = 0.3  # 0.003%, buy side only (approximated: both)
_KITE_BROKERAGE_INTRADAY_BPS: Final = 3.0  # 0.03%, capped at Rs 20/order
_KITE_BROKERAGE_INTRADAY_CAP_RUPEES: Final = 20.0
_KITE_GST_ON_CHARGES_DELIVERY_BPS: Final = (
    _KITE_EXCHANGE_TXN_BPS + _KITE_SEBI_BPS
) * 0.18  # 18% of exchange + SEBI charges (delivery brokerage is Rs 0, no GST base there)

_GROWW_STT_DELIVERY_BPS: Final = 10.0  # 0.1%, both sides
_GROWW_STT_INTRADAY_BPS: Final = 2.5  # 0.025%, sell side only (approximated: both)
_GROWW_EXCHANGE_TXN_BPS: Final = 0.297  # 0.00297%, both sides
_GROWW_SEBI_BPS: Final = 0.01  # 0.0001%, both sides
_GROWW_STAMP_DUTY_DELIVERY_BPS: Final = 1.5  # 0.015%, buy side only (approximated: both)
_GROWW_STAMP_DUTY_INTRADAY_BPS: Final = 0.3  # 0.003%, buy side only (approximated: both)
_GROWW_BROKERAGE_BPS: Final = 10.0  # 0.1%, capped at Rs 20/order (same rate both segments)
_GROWW_BROKERAGE_CAP_RUPEES: Final = 20.0
_GROWW_DP_CHARGE_RUPEES: Final = 16.5  # sell side only (approximated: every fill)


def _bps_of_notional(quantity: int, price: float, bps: float) -> float:
    return price * quantity * bps / 10_000


def kite_delivery_cost(quantity: int, price: float) -> float:
    """Zerodha equity delivery: Rs 0 brokerage, but STT/exchange/SEBI/
    stamp-duty/GST still apply on every fill.
    """
    return (
        _bps_of_notional(quantity, price, _KITE_STT_DELIVERY_BPS)
        + _bps_of_notional(quantity, price, _KITE_EXCHANGE_TXN_BPS)
        + _bps_of_notional(quantity, price, _KITE_SEBI_BPS)
        + _bps_of_notional(quantity, price, _KITE_STAMP_DUTY_DELIVERY_BPS)
        + _bps_of_notional(quantity, price, _KITE_GST_ON_CHARGES_DELIVERY_BPS)
    )


def kite_intraday_cost(quantity: int, price: float) -> float:
    """Zerodha equity intraday: brokerage capped at min(0.03% of notional,
    Rs 20/order), plus STT/exchange/SEBI/stamp-duty on every fill.
    """
    brokerage = min(
        _bps_of_notional(quantity, price, _KITE_BROKERAGE_INTRADAY_BPS),
        _KITE_BROKERAGE_INTRADAY_CAP_RUPEES,
    )
    return (
        brokerage
        + _bps_of_notional(quantity, price, _KITE_STT_INTRADAY_BPS)
        + _bps_of_notional(quantity, price, _KITE_EXCHANGE_TXN_BPS)
        + _bps_of_notional(quantity, price, _KITE_SEBI_BPS)
        + _bps_of_notional(quantity, price, _KITE_STAMP_DUTY_INTRADAY_BPS)
    )


def groww_delivery_cost(quantity: int, price: float) -> float:
    """Groww equity delivery: brokerage capped at min(0.1% of notional,
    Rs 20/order) since Groww's mid-2024 pricing change (no longer free),
    plus STT/exchange/SEBI/stamp-duty and a flat Rs 16.5 DP charge.
    """
    brokerage = min(
        _bps_of_notional(quantity, price, _GROWW_BROKERAGE_BPS),
        _GROWW_BROKERAGE_CAP_RUPEES,
    )
    return (
        brokerage
        + _bps_of_notional(quantity, price, _GROWW_STT_DELIVERY_BPS)
        + _bps_of_notional(quantity, price, _GROWW_EXCHANGE_TXN_BPS)
        + _bps_of_notional(quantity, price, _GROWW_SEBI_BPS)
        + _bps_of_notional(quantity, price, _GROWW_STAMP_DUTY_DELIVERY_BPS)
        + _GROWW_DP_CHARGE_RUPEES
    )


def groww_intraday_cost(quantity: int, price: float) -> float:
    """Groww equity intraday: brokerage capped at min(0.1% of notional,
    Rs 20/order), plus STT/exchange/SEBI/stamp-duty on every fill. No DP
    charge (that only applies to a delivery sell).
    """
    brokerage = min(
        _bps_of_notional(quantity, price, _GROWW_BROKERAGE_BPS),
        _GROWW_BROKERAGE_CAP_RUPEES,
    )
    return (
        brokerage
        + _bps_of_notional(quantity, price, _GROWW_STT_INTRADAY_BPS)
        + _bps_of_notional(quantity, price, _GROWW_EXCHANGE_TXN_BPS)
        + _bps_of_notional(quantity, price, _GROWW_SEBI_BPS)
        + _bps_of_notional(quantity, price, _GROWW_STAMP_DUTY_INTRADAY_BPS)
    )


def slippage_fill_price(price: float, side: str, bps: float) -> float:
    """Shifts the fill price against the trader by bps basis points: a
    buy pays a worse (higher) price, a sell receives a worse (lower)
    price. bps=0.0 (the default cost profile) returns price unchanged.
    """
    direction = 1 if side == "buy" else -1
    return price * (1 + direction * bps / 10_000)
