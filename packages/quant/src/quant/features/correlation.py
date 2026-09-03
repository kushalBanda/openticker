import statistics
from itertools import combinations

from quant.core.exceptions import InsufficientDataError


def rolling_correlation_matrix(
    closes_by_symbol: dict[str, list[float]], window: int
) -> dict[tuple[str, str], float]:
    """Pearson correlation of period-over-period returns over the last
    `window` closes, for every symbol pair present in closes_by_symbol.

    Diagonal (symbol, symbol) entries are always 1.0. Raises
    InsufficientDataError if any symbol has fewer than window + 1 closes.
    """
    returns_by_symbol: dict[str, list[float]] = {}
    for symbol, closes in closes_by_symbol.items():
        if len(closes) < window + 1:
            raise InsufficientDataError(
                f"rolling_correlation_matrix needs at least {window + 1} closes "
                f"for {symbol!r}, got {len(closes)}"
            )
        recent = closes[-(window + 1) :]
        returns_by_symbol[symbol] = [
            (recent[i] - recent[i - 1]) / recent[i - 1]
            for i in range(1, len(recent))
            if recent[i - 1] != 0
        ]

    matrix: dict[tuple[str, str], float] = {
        (symbol, symbol): 1.0 for symbol in closes_by_symbol
    }
    for symbol_a, symbol_b in combinations(closes_by_symbol, 2):
        correlation = statistics.correlation(
            returns_by_symbol[symbol_a], returns_by_symbol[symbol_b]
        )
        matrix[(symbol_a, symbol_b)] = correlation
        matrix[(symbol_b, symbol_a)] = correlation
    return matrix
