"""evaluate_signal MCP tool (quant-engine server): does a signal predict forward returns?

The first caller of quant.evaluation.evaluator - that module existed
tested but unused in the interactive layer until this tool (see
docs/superpowers/specs/2026-09-11-quant-engine-mcp-design.md's Problem
section).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import Field
from quant.core.registry import SignalFactory
from quant.evaluation.evaluator import evaluate_signal as evaluate_signal_report

from engine.core.data import connect_engine, fetch_symbol_bars
from engine.core.exceptions import InvalidSignalParamsError
from engine.core.serialization import to_json_dict


async def evaluate_signal(
    signal: Annotated[
        str, Field(description='Registered signal name, e.g. "rsi", "sma", "above_average_volume".')
    ],
    symbol: Annotated[str, Field(description='Tradingsymbol to evaluate, e.g. "RELIANCE".')],
    horizon: Annotated[
        int, Field(description="Number of bars ahead to measure the forward return over. Must be > 0.", gt=0)
    ],
    min_lookback: Annotated[
        int,
        Field(
            description=(
                "Smallest bar window the signal's compute() needs to produce a valid "
                'value - e.g. period + 1 for "rsi", window for "sma". Caller must work '
                "this out; it is not inferred from the signal name."
            ),
            gt=0,
        ),
    ],
    params: Annotated[
        dict[str, float | int] | None,
        Field(
            description=(
                'Constructor kwargs for the chosen signal, e.g. {"period": 14} for "rsi". '
                "Omit or pass {} for signals with no constructor args."
            )
        ),
    ] = None,
    interval: Annotated[
        str, Field(description='Canonical bar interval, e.g. "1d", "1m".')
    ] = "1d",
    days: Annotated[
        int, Field(description="Lookback window in days from now, for the bars fetched.", gt=0)
    ] = 365,
    provider: Annotated[
        str | None,
        Field(
            description=(
                'Provider name, e.g. "kite". Omit to use whichever provider connected '
                "most recently."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """Evaluate whether a signal predicts forward returns on real bars.

    Returns:
        The serialized SignalEvaluationReport: information_coefficient,
        ic_p_value, effective_ic_p_value, turnover_proxy, sample sizes,
        and the overlapping-windows caveat.

    Raises:
        engine.core.exceptions.NotConnectedError: No adapter is connected.
        engine.core.exceptions.SessionExpiredError: The stored session expired.
        engine.core.exceptions.ProviderRateLimitedError: The provider
            rejected a connect/fetch call for exceeding its rate limit.
        engine.core.exceptions.InvalidSignalParamsError: params don't
            match the signal's constructor.
        quant.core.exceptions.UnknownSignalError: Unregistered signal name.
        quant.core.exceptions.InsufficientDataError: Not enough valid
            (signal, forward return) pairs to evaluate.
    """
    resolved_params = params or {}
    try:
        signal_instance = SignalFactory.create(signal, resolved_params)
    except TypeError as exc:
        raise InvalidSignalParamsError(
            f"bad params for signal {signal!r}: {exc}. Check "
            "plugin/references for this signal's expected constructor args."
        ) from None

    resolved_provider, data_engine = await connect_engine(provider)
    to = datetime.now(UTC)
    frm = to - timedelta(days=days)
    bars = await fetch_symbol_bars(data_engine, resolved_provider, symbol, interval, frm, to)

    report = evaluate_signal_report(signal_instance, bars, horizon, min_lookback)
    return dict(to_json_dict(report))
