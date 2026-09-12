#!/usr/bin/env python3
"""evaluate-signal skill script: does a signal predict forward returns?

Run as: uv run python plugin/skills/evaluate-signal/scripts/evaluate_signal.py \
    --signal rsi --symbol RELIANCE --horizon 5 --min-lookback 15 \
    --params '{"period": 14}' [--interval 1d] [--days 365] [--provider kite]

Prints one JSON object: the serialized SignalEvaluationReport, or
{"error": "..."} on failure.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.math.evaluation import evaluate_signal_ic
from lib.math.exceptions import InsufficientDataError
from lib.math.indicators import (
    compute_above_average_volume,
    compute_rsi,
    compute_sma,
    compute_time_series_momentum,
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

_SIGNAL_COMPUTE = {
    "rsi": lambda window, params: compute_rsi(window, period=int(params["period"])),
    "sma": lambda window, params: compute_sma(window, window=int(params["window"])),
    "above_average_volume": lambda window, params: compute_above_average_volume(
        window, window=int(params["window"])
    ),
    "time_series_momentum": lambda window, params: compute_time_series_momentum(
        window, window=int(params["window"])
    ),
}


async def _run(
    signal: str,
    symbol: str,
    horizon: int,
    min_lookback: int,
    params: dict[str, float | int],
    interval: str,
    days: int,
    provider: str | None,
) -> dict[str, object]:
    compute_fn = _SIGNAL_COMPUTE.get(signal)
    if compute_fn is None:
        raise ValueError(f"unknown signal {signal!r} - available: {sorted(_SIGNAL_COMPUTE)}")

    resolved_provider, creds = _resolve_provider(provider)
    store = DuckDBStore()
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    bars: list[Bar] = await fetch_symbol_bars(store, resolved_provider, creds, symbol, interval, frm, to)

    def compute(window: list[Bar]):  # type: ignore[no-untyped-def]
        return compute_fn(window, params)

    report = evaluate_signal_ic(compute, signal, bars, horizon, min_lookback)
    return dict(asdict(report))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--horizon", type=int, required=True)
    parser.add_argument("--min-lookback", type=int, required=True)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(
            _run(
                args.signal,
                args.symbol,
                args.horizon,
                args.min_lookback,
                json.loads(args.params),
                args.interval,
                args.days,
                args.provider,
            )
        )
    except (
        ValueError,
        TypeError,
        NotConnectedError,
        AuthExpiredError,
        RateLimitError,
        DataUnavailableError,
        InsufficientDataError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
