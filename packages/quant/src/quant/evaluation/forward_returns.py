from ingest.core.models import Bar


def forward_returns(bars: list[Bar], horizon: int) -> list[float | None]:
    """Compute the N-day forward return for every bar in ``bars``.

    Entry i is ``close[i + horizon] / close[i] - 1``. The last ``horizon``
    entries are ``None`` since no future bar exists yet to compute against.

    Args:
        bars: bars sorted ascending by timestamp.
        horizon: number of bars ahead to measure the return over. Must be
            greater than 0.

    Returns:
        One entry per bar in ``bars``, same length and order.

    Raises:
        ValueError: if horizon is not greater than 0.
    """
    if horizon <= 0:
        raise ValueError("horizon must be greater than 0")

    returns: list[float | None] = []
    last_valid_index = len(bars) - horizon
    for i, bar in enumerate(bars):
        if i >= last_valid_index:
            returns.append(None)
            continue
        future_close = bars[i + horizon].close
        returns.append(future_close / bar.close - 1)
    return returns
