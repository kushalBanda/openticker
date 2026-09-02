import statistics

from quant.core.exceptions import InsufficientDataError


def realized_volatility(closes: list[float]) -> float:
    """Population stdev of simple period-over-period returns.

    Realized volatility, not a GARCH/EWMA estimate (that's `arch`'s job,
    per the HLD — deliberately not pulled in yet, same reasoning as
    simple_rsi not needing `ta`: add the heavier dependency when something
    actually needs its extra accuracy, not preemptively).
    """
    if len(closes) < 2:
        raise InsufficientDataError(
            f"realized_volatility needs at least 2 closes, got {len(closes)}"
        )
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]
    if not returns:
        raise InsufficientDataError("realized_volatility got no valid non-zero closes")
    return statistics.pstdev(returns)
