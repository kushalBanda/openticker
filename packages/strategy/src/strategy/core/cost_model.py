from typing import Final, Literal, Protocol

from strategy.core.constants import ORDER_SIDE_BUY


class TransactionCostModel(Protocol):
    """Answers one question: what does this fill cost in commission
    dollars. Carries no price-impact logic, that belongs to a
    `SlippageModel` (below), kept separate so cost assumptions can
    change without touching how the fill price itself is computed.
    """

    def get_cost(self, quantity: int, price: float) -> float: ...


class SlippageModel(Protocol):
    """Answers one question: what price does this order actually fill
    at, given market impact. Carries no commission logic, that belongs
    to a `TransactionCostModel` (above).
    """

    def get_fill_price(self, price: float, side: str) -> float: ...


class PerShareFeeModel:
    """Fixed commission per share traded, independent of price."""

    def __init__(self, cost_per_share: float) -> None:
        self._cost_per_share = cost_per_share

    def get_cost(self, quantity: int, price: float) -> float:
        return quantity * self._cost_per_share


class FlatFeeModel:
    """Fixed commission per order, independent of quantity and price."""

    def __init__(self, fee: float) -> None:
        self._fee = fee

    def get_cost(self, quantity: int, price: float) -> float:
        return self._fee


class PercentOfNotionalModel:
    """Commission scaled by trade notional (price * quantity), in basis
    points, e.g. a percent-of-turnover brokerage or a statutory charge.
    """

    def __init__(self, bps: float) -> None:
        self._bps = bps

    def get_cost(self, quantity: int, price: float) -> float:
        return price * quantity * self._bps / 10_000


class AggregateCostModel:
    """Combines several `TransactionCostModel`s into one, e.g. a broker's
    "0.1% of notional or a flat cap, whichever is lower" brokerage rule:
    `AggregateCostModel((PercentOfNotionalModel(10.0), FlatFeeModel(20.0)), aggregate="min")`.
    """

    def __init__(
        self,
        models: tuple[TransactionCostModel, ...],
        aggregate: Literal["sum", "min", "max"] = "sum",
    ) -> None:
        self._models = models
        self._aggregate = aggregate

    def get_cost(self, quantity: int, price: float) -> float:
        costs = [m.get_cost(quantity, price) for m in self._models]
        if self._aggregate == "sum":
            return sum(costs)
        if self._aggregate == "min":
            return min(costs)
        if self._aggregate == "max":
            return max(costs)
        raise ValueError(f"unrecognized aggregate type: {self._aggregate!r}")


class BpsSlippageModel:
    """Shifts the fill price against the trader by `bps` basis points:
    a buy pays a worse (higher) price, a sell receives a worse (lower)
    price, a realistic one-sided model of market impact.
    """

    def __init__(self, bps: float) -> None:
        self._bps = bps

    def get_fill_price(self, price: float, side: str) -> float:
        direction = 1 if side == ORDER_SIDE_BUY else -1
        return price * (1 + direction * self._bps / 10_000)


# Real Kite (Zerodha) and Groww equity charge schedules, verified against
# zerodha.com/charges and groww.in/pricing (fetched 2026-09-12). STT and
# exchange/SEBI charges are applied on every fill even though the real
# schedules charge some components on one side only (STT sell-only for
# intraday, stamp duty buy-only, DP charge sell-only for Groww) - a
# same-rate-both-sides approximation, disclosed here rather than modeled
# exactly, since `TransactionCostModel.get_cost` has no side parameter and
# the error is small next to the dominant STT/brokerage terms. GST (18% on
# brokerage + exchange + SEBI charges) is folded into the delivery presets
# exactly (Kite's delivery brokerage is always Rs 0, so GST's base there is
# fixed) and approximated in the intraday presets (brokerage there is a
# variable capped amount, so GST-on-brokerage is left out as a disclosed
# small under-estimate).
_KITE_STT_DELIVERY_BPS: Final = 10.0  # 0.1%, both sides
_KITE_STT_INTRADAY_BPS: Final = 2.5  # 0.025%, sell side only (approximated: both)
_KITE_EXCHANGE_TXN_BPS: Final = 0.307  # 0.00307%, both sides
_KITE_SEBI_BPS: Final = 0.01  # 0.0001%, both sides
_KITE_STAMP_DUTY_DELIVERY_BPS: Final = 1.5  # 0.015%, buy side only (approximated: both)
_KITE_STAMP_DUTY_INTRADAY_BPS: Final = 0.3  # 0.003%, buy side only (approximated: both)
_KITE_BROKERAGE_INTRADAY_BPS: Final = 3.0  # 0.03%, capped at Rs 20/order
_KITE_BROKERAGE_INTRADAY_CAP_RUPEES: Final = 20.0
_KITE_GST_ON_CHARGES_DELIVERY_BPS: Final = (
    (_KITE_EXCHANGE_TXN_BPS + _KITE_SEBI_BPS) * 0.18
)  # 18% of exchange + SEBI charges (delivery brokerage is Rs 0, no GST base there)

_GROWW_STT_DELIVERY_BPS: Final = 10.0  # 0.1%, both sides
_GROWW_STT_INTRADAY_BPS: Final = 2.5  # 0.025%, sell side only (approximated: both)
_GROWW_EXCHANGE_TXN_BPS: Final = 0.297  # 0.00297%, both sides
_GROWW_SEBI_BPS: Final = 0.01  # 0.0001%, both sides
_GROWW_STAMP_DUTY_DELIVERY_BPS: Final = 1.5  # 0.015%, buy side only (approximated: both)
_GROWW_STAMP_DUTY_INTRADAY_BPS: Final = 0.3  # 0.003%, buy side only (approximated: both)
_GROWW_BROKERAGE_BPS: Final = 10.0  # 0.1%, capped at Rs 20/order (same rate both segments)
_GROWW_BROKERAGE_CAP_RUPEES: Final = 20.0
_GROWW_DP_CHARGE_RUPEES: Final = 16.5  # sell side only (approximated: every fill)


def kite_delivery_cost_model() -> TransactionCostModel:
    """Zerodha equity delivery: Rs 0 brokerage, but STT/exchange/SEBI/
    stamp-duty/GST still apply on every fill (see module comment above)."""
    return AggregateCostModel(
        (
            PercentOfNotionalModel(_KITE_STT_DELIVERY_BPS),
            PercentOfNotionalModel(_KITE_EXCHANGE_TXN_BPS),
            PercentOfNotionalModel(_KITE_SEBI_BPS),
            PercentOfNotionalModel(_KITE_STAMP_DUTY_DELIVERY_BPS),
            PercentOfNotionalModel(_KITE_GST_ON_CHARGES_DELIVERY_BPS),
        )
    )


def kite_intraday_cost_model() -> TransactionCostModel:
    """Zerodha equity intraday: brokerage capped at min(0.03% of notional,
    Rs 20/order), plus STT/exchange/SEBI/stamp-duty on every fill."""
    return AggregateCostModel(
        (
            AggregateCostModel(
                (
                    PercentOfNotionalModel(_KITE_BROKERAGE_INTRADAY_BPS),
                    FlatFeeModel(_KITE_BROKERAGE_INTRADAY_CAP_RUPEES),
                ),
                aggregate="min",
            ),
            PercentOfNotionalModel(_KITE_STT_INTRADAY_BPS),
            PercentOfNotionalModel(_KITE_EXCHANGE_TXN_BPS),
            PercentOfNotionalModel(_KITE_SEBI_BPS),
            PercentOfNotionalModel(_KITE_STAMP_DUTY_INTRADAY_BPS),
        )
    )


def groww_delivery_cost_model() -> TransactionCostModel:
    """Groww equity delivery: brokerage capped at min(0.1% of notional,
    Rs 20/order) since Groww's mid-2024 pricing change (no longer free),
    plus STT/exchange/SEBI/stamp-duty and a flat Rs 16.5 DP charge."""
    return AggregateCostModel(
        (
            AggregateCostModel(
                (
                    PercentOfNotionalModel(_GROWW_BROKERAGE_BPS),
                    FlatFeeModel(_GROWW_BROKERAGE_CAP_RUPEES),
                ),
                aggregate="min",
            ),
            PercentOfNotionalModel(_GROWW_STT_DELIVERY_BPS),
            PercentOfNotionalModel(_GROWW_EXCHANGE_TXN_BPS),
            PercentOfNotionalModel(_GROWW_SEBI_BPS),
            PercentOfNotionalModel(_GROWW_STAMP_DUTY_DELIVERY_BPS),
            FlatFeeModel(_GROWW_DP_CHARGE_RUPEES),
        )
    )


def groww_intraday_cost_model() -> TransactionCostModel:
    """Groww equity intraday: brokerage capped at min(0.1% of notional,
    Rs 20/order), plus STT/exchange/SEBI/stamp-duty on every fill. No DP
    charge (that only applies to a delivery sell)."""
    return AggregateCostModel(
        (
            AggregateCostModel(
                (
                    PercentOfNotionalModel(_GROWW_BROKERAGE_BPS),
                    FlatFeeModel(_GROWW_BROKERAGE_CAP_RUPEES),
                ),
                aggregate="min",
            ),
            PercentOfNotionalModel(_GROWW_STT_INTRADAY_BPS),
            PercentOfNotionalModel(_GROWW_EXCHANGE_TXN_BPS),
            PercentOfNotionalModel(_GROWW_SEBI_BPS),
            PercentOfNotionalModel(_GROWW_STAMP_DUTY_INTRADAY_BPS),
        )
    )
