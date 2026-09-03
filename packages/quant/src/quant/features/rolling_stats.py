from quant.core.exceptions import InsufficientDataError


def average_volume(volumes: list[int], window: int) -> float:
    if len(volumes) < window:
        raise InsufficientDataError(
            f"average_volume needs at least {window} volumes, got {len(volumes)}"
        )
    return sum(volumes[-window:]) / window


def simple_moving_average(closes: list[float], window: int) -> float:
    if len(closes) < window:
        raise InsufficientDataError(
            f"simple_moving_average needs at least {window} closes, got {len(closes)}"
        )
    return sum(closes[-window:]) / window


def simple_rsi(closes: list[float], period: int) -> float:
    """Simple moving-average RSI: gains/losses averaged over a flat rolling
    window, NOT Wilder's original recursive exponential smoothing. Values
    from this function will not match Kite's charts, TradingView, or the
    `ta` library's default RSI, all of which use Wilder smoothing. Kept as
    this variant deliberately, since it's what RsiMeanReversionStrategy
    already computed inline before this signal existed, and the migration
    to RsiSignal must reproduce the same backtest output bit for bit.
    """
    if len(closes) < period + 1:
        raise InsufficientDataError(
            f"simple_rsi needs at least {period + 1} closes, got {len(closes)}"
        )
    window = closes[-(period + 1) :]
    gains = [max(window[i] - window[i - 1], 0.0) for i in range(1, len(window))]
    losses = [max(window[i - 1] - window[i], 0.0) for i in range(1, len(window))]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
