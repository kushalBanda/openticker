import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.correlation import rolling_correlation_matrix


def test_perfectly_correlated_series_gives_one() -> None:
    a = [100.0, 102.0, 104.04, 106.1208, 108.243216]  # +2% every step
    b = [50.0, 51.0, 52.02, 53.0604, 54.121608]  # +2% every step, same shape

    matrix = rolling_correlation_matrix({"A": a, "B": b}, window=4)

    assert matrix[("A", "B")] == pytest.approx(1.0, abs=1e-6)
    assert matrix[("B", "A")] == pytest.approx(1.0, abs=1e-6)


def test_perfectly_anticorrelated_series_gives_minus_one() -> None:
    # A's returns: +2%, -1%, +3%, -2%. B mirrors the exact negative of each.
    a = [100.0, 102.0, 100.98, 104.0094, 101.929212]
    b = [50.0, 49.0, 49.49, 48.0053, 48.965406]

    matrix = rolling_correlation_matrix({"A": a, "B": b}, window=4)

    assert matrix[("A", "B")] == pytest.approx(-1.0, abs=1e-6)


def test_diagonal_entries_are_one() -> None:
    a = [100.0, 101.0, 99.0, 102.0]
    matrix = rolling_correlation_matrix({"A": a}, window=3)

    assert matrix[("A", "A")] == 1.0


def test_raises_when_insufficient_closes_for_window() -> None:
    with pytest.raises(InsufficientDataError):
        rolling_correlation_matrix({"A": [100.0, 101.0], "B": [50.0, 51.0]}, window=5)
