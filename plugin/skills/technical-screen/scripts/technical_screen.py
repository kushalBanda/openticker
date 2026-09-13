#!/usr/bin/env python3
"""technical-screen skill script: an open technical-indicator dispatch.

Run as: uv run python plugin/skills/technical-screen/scripts/technical_screen.py \
    --symbol RELIANCE --indicators rsi,ema,breakout \
    [--params '{"ema": {"period": 200}}'] [--benchmark-symbol NIFTY50] \
    [--interval 1d] [--days 400] [--provider kite]

Prints one JSON object keyed by indicator name: {"value": ..., "params_used":
{...}} on success, {"error": "...", "params_used": {...}} if that one
indicator's bars were insufficient. An unknown indicator name or a missing
--benchmark-symbol for a cross-sectional indicator is reported the same
way, per-indicator, without failing the rest of the request.
"""

import argparse
import asyncio
import inspect
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.cross_sectional import (
    compute_beta,
    compute_correlation,
    compute_pairs_spread,
    compute_relative_strength,
)
from lib.math.indicators.momentum import (
    compute_cci,
    compute_roc,
    compute_rsi,
    compute_stochastic,
    compute_stochastic_rsi,
    compute_williams_r,
)
from lib.math.indicators.structure import (
    compute_52_week_range_position,
    compute_breakout,
    compute_candlestick_pattern,
    compute_gap,
    compute_pivot_points,
    compute_support_resistance,
)
from lib.math.indicators.trend import (
    compute_adx,
    compute_ema,
    compute_macd,
    compute_parabolic_sar,
    compute_sma,
    compute_wma,
)
from lib.math.indicators.volatility import (
    compute_atr,
    compute_bollinger_bands,
    compute_realized_volatility,
)
from lib.math.indicators.volume import (
    compute_above_average_volume,
    compute_accumulation_distribution,
    compute_obv,
    compute_vwap,
)
from lib.mechanics.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    NotConnectedError,
    RateLimitError,
)
from lib.mechanics.models import Bar
from lib.mechanics.store import DuckDBStore

sys.path.insert(0, str(_PLUGIN_ROOT / "skills" / "fetch-bars" / "scripts"))
from fetch_bars import _resolve_provider, fetch_symbol_bars

_SINGLE_SERIES_INDICATORS: dict[str, Callable[..., Any]] = {
    "sma": compute_sma,
    "ema": compute_ema,
    "wma": compute_wma,
    "macd": compute_macd,
    "adx": compute_adx,
    "parabolic_sar": compute_parabolic_sar,
    "rsi": compute_rsi,
    "stochastic": compute_stochastic,
    "stochastic_rsi": compute_stochastic_rsi,
    "williams_r": compute_williams_r,
    "roc": compute_roc,
    "cci": compute_cci,
    "bollinger_bands": compute_bollinger_bands,
    "atr": compute_atr,
    "realized_volatility": compute_realized_volatility,
    "above_average_volume": compute_above_average_volume,
    "obv": compute_obv,
    "vwap": compute_vwap,
    "accumulation_distribution": compute_accumulation_distribution,
    "breakout": compute_breakout,
    "support_resistance": compute_support_resistance,
    "candlestick_pattern": compute_candlestick_pattern,
    "gap": compute_gap,
    "fifty_two_week_range_position": compute_52_week_range_position,
    "pivot_points": compute_pivot_points,
}

_CROSS_SECTIONAL_INDICATORS: dict[str, Callable[..., Any]] = {
    "relative_strength": compute_relative_strength,
    "correlation": compute_correlation,
    "beta": compute_beta,
    "pairs_spread": compute_pairs_spread,
}


def _resolve_params(fn: Callable[..., Any], overrides: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name in ("bars", "benchmark_bars", "bars_a", "bars_b"):
            continue
        if param.default is not inspect.Parameter.empty:
            resolved[name] = param.default
    resolved.update(overrides)
    return resolved


def _serialize(value: Any) -> Any:
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else value


def build_indicator_report(
    bars: list[Bar],
    benchmark_bars: list[Bar] | None,
    indicator_names: list[str],
    params_by_indicator: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in indicator_names:
        overrides = params_by_indicator.get(name, {})
        if name in _CROSS_SECTIONAL_INDICATORS:
            fn = _CROSS_SECTIONAL_INDICATORS[name]
            params = _resolve_params(fn, overrides)
            if benchmark_bars is None:
                report[name] = {"error": f"{name} needs --benchmark-symbol", "params_used": params}
                continue
            try:
                value = fn(bars, benchmark_bars, **params)
            except (InsufficientDataError, ValueError) as exc:
                report[name] = {"error": str(exc), "params_used": params}
                continue
            report[name] = {"value": _serialize(value), "params_used": params}
            continue

        single_fn = _SINGLE_SERIES_INDICATORS.get(name)
        if single_fn is None:
            report[name] = {"error": f"unknown indicator {name!r} - available: {sorted(_SINGLE_SERIES_INDICATORS) + sorted(_CROSS_SECTIONAL_INDICATORS)}"}
            continue
        params = _resolve_params(single_fn, overrides)
        try:
            value = single_fn(bars, **params)
        except (InsufficientDataError, ValueError) as exc:
            report[name] = {"error": str(exc), "params_used": params}
            continue
        report[name] = {"value": _serialize(value), "params_used": params}
    return report


async def _run(
    symbol: str, indicator_names: list[str], params_by_indicator: dict[str, dict[str, Any]],
    benchmark_symbol: str | None, interval: str, days: int, provider: str | None,
) -> dict[str, Any]:
    resolved_provider, creds = _resolve_provider(provider)
    store = DuckDBStore()
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    bars = await fetch_symbol_bars(store, resolved_provider, creds, symbol, interval, frm, to)

    benchmark_bars: list[Bar] | None = None
    if benchmark_symbol:
        benchmark_bars = await fetch_symbol_bars(store, resolved_provider, creds, benchmark_symbol, interval, frm, to)

    report = build_indicator_report(bars, benchmark_bars, indicator_names, params_by_indicator)
    return {"symbol": symbol, "indicators": report}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--indicators", required=True, help="comma-separated indicator names")
    parser.add_argument("--params", default="{}", help='JSON: {"ema": {"period": 200}}')
    parser.add_argument("--benchmark-symbol", default=None)
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    indicator_names = [name.strip() for name in args.indicators.split(",") if name.strip()]
    try:
        params_by_indicator = json.loads(args.params)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"--params was not valid JSON: {exc}"}))
        return 1

    try:
        result = asyncio.run(
            _run(args.symbol, indicator_names, params_by_indicator, args.benchmark_symbol, args.interval, args.days, args.provider)
        )
    except (NotConnectedError, DataUnavailableError, AuthExpiredError, RateLimitError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
