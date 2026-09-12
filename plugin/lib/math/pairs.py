"""Gatev, Goetzmann & Rouwenhorst pairs-trading math: sum-of-squared-deviation
pair ranking over a normalized formation window, and a frozen-baseline
spread z-score for the trading window that follows.

Ported verbatim from quant.features.pairs.
"""

from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from lib.math.econometrics import index_normalize
from lib.math.exceptions import InsufficientDataError


@dataclass(frozen=True)
class Pair:
    symbol_a: str
    symbol_b: str
    anchor_a: float
    anchor_b: float
    ssd: float


@dataclass(frozen=True)
class SpreadBaseline:
    mean: float
    std: float


def _anchor(closes: pd.Series) -> float:
    first_idx = closes.first_valid_index()
    if first_idx is None:
        raise InsufficientDataError("closes series has no valid observations")
    return float(closes.loc[first_idx])


def select_pairs(closes: dict[str, pd.Series], top_n: int) -> list[Pair]:
    usable = {symbol: series for symbol, series in closes.items() if not series.dropna().empty}
    if len(usable) < 2:
        raise InsufficientDataError(f"select_pairs needs at least 2 usable symbols, got {len(usable)}")

    normalized = {symbol: index_normalize(series) for symbol, series in usable.items()}
    anchors = {symbol: _anchor(series) for symbol, series in usable.items()}

    pairs: list[Pair] = []
    for symbol_a, symbol_b in combinations(sorted(usable), 2):
        aligned = pd.concat([normalized[symbol_a], normalized[symbol_b]], axis=1, join="inner").dropna()
        if len(aligned) < 2:
            continue
        ssd = float(((aligned.iloc[:, 0] - aligned.iloc[:, 1]) ** 2).sum())
        pairs.append(
            Pair(
                symbol_a=symbol_a,
                symbol_b=symbol_b,
                anchor_a=anchors[symbol_a],
                anchor_b=anchors[symbol_b],
                ssd=ssd,
            )
        )

    pairs.sort(key=lambda pair: pair.ssd)
    return pairs[:top_n]


def spread_baseline(
    closes_a: pd.Series, closes_b: pd.Series, anchor_a: float, anchor_b: float
) -> SpreadBaseline:
    aligned = pd.concat([closes_a, closes_b], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        raise InsufficientDataError(f"spread_baseline needs at least 2 aligned observations, got {len(aligned)}")
    spread = aligned.iloc[:, 0] / anchor_a - aligned.iloc[:, 1] / anchor_b
    std = float(spread.std())
    if std == 0:
        raise InsufficientDataError("spread_baseline needs a nonzero spread standard deviation")
    return SpreadBaseline(mean=float(spread.mean()), std=std)


def spread_value(price_a: float, price_b: float, anchor_a: float, anchor_b: float) -> float:
    """Single-point normalized spread, using the same frozen anchors
    spread_baseline was built from, never re-anchored mid trading period.
    """
    return price_a / anchor_a - price_b / anchor_b


def zscore(value: float, baseline: SpreadBaseline) -> float:
    return (value - baseline.mean) / baseline.std
