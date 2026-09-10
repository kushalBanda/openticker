def capital_to_quantity(capital: float, price: float) -> int:
    """Whole shares affordable with `capital` at `price`, floored, never
    negative. Shared by every strategy that turns a cash budget into an
    order quantity (`pairs_trading`, `time_series_momentum`).
    """
    if price <= 0:
        return 0
    return max(0, int(capital // price))
