from http import HTTPStatus
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from ingest.core.engine import DataEngine
from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.core.registry import StrategyFactory, list_strategy_names
from strategy.metrics.performance import compute_metrics
from strategy.storage.ledger_store import LedgerStore

from server.core.constants import API_PREFIX_BACKTEST
from server.core.deps import get_data_engine, get_ledger_store
from server.schemas.backtest import (
    BacktestRequest,
    BacktestRequestBase,
    BacktestRunOut,
    LedgerEntryOut,
    PerformanceReportOut,
    RunListOut,
    StrategyListOut,
)

router = APIRouter(prefix=API_PREFIX_BACKTEST, tags=["backtests"])

# /backtest and /strategies aren't under the /backtests prefix above,
# which is for reading past runs — mounted separately in app.py.
action_router = APIRouter(tags=["backtests"])


def _strategy_params(request: BacktestRequest) -> dict[str, object]:
    extra_fields = set(type(request).model_fields) - set(
        BacktestRequestBase.model_fields
    ) - {"strategy_name"}
    return request.model_dump(include=extra_fields)


async def _fetch_bars(
    request: BacktestRequest, engine: DataEngine
) -> dict[str, list[Bar]]:
    bars: dict[str, list[Bar]] = {}
    for symbol in request.symbols:
        symbol_bars = await engine.fetch_historical(
            symbol, request.interval, request.from_, request.to
        )
        if not symbol_bars:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=(
                    f"no bars for symbol {symbol!r}, interval "
                    f"{request.interval!r} in the requested range"
                ),
            )
        bars[symbol] = symbol_bars
    return bars


@action_router.post("/backtest", response_model=BacktestRunOut)
async def run_backtest(
    request: BacktestRequest,
    data_engine: DataEngine = Depends(get_data_engine),
    ledger_store: LedgerStore = Depends(get_ledger_store),
) -> BacktestRunOut:
    bars = await _fetch_bars(request, data_engine)
    strategy = StrategyFactory.create(
        request.strategy_name, _strategy_params(request)
    )

    broker_kwargs: dict[str, float] = {}
    if request.slippage_bps is not None:
        broker_kwargs["slippage_bps"] = request.slippage_bps
    if request.commission_per_share is not None:
        broker_kwargs["commission_per_share"] = request.commission_per_share
    broker = BacktestBroker(**broker_kwargs)

    portfolio = Portfolio(starting_cash=request.starting_cash)
    engine = BacktestEngine(broker, portfolio)
    await engine.run(bars, strategy)

    run_id = str(uuid4())
    ledger_store.write_entries(run_id, portfolio.ledger.entries)
    return BacktestRunOut(run_id=run_id, trade_count=len(portfolio.ledger.entries))


@action_router.get("/strategies", response_model=StrategyListOut)
def get_strategies() -> StrategyListOut:
    return StrategyListOut(strategy_names=list_strategy_names())


def _entries_or_404(
    run_id: str, store: LedgerStore
) -> list[LedgerEntryOut]:
    entries = store.query_entries(run_id)
    if not entries:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"no ledger entries for run_id {run_id!r}",
        )
    return [
        LedgerEntryOut(
            symbol=e.symbol,
            side=e.side,
            quantity=e.quantity,
            fill_price=e.fill_price,
            fill_ts=e.fill_ts,
            commission=e.commission,
            cost_basis_before=e.cost_basis_before,
            realized_pnl=e.realized_pnl,
            cash_after=e.cash_after,
            position_after=e.position_after,
        )
        for e in entries
    ]


@router.get("", response_model=RunListOut)
def list_runs(store: LedgerStore = Depends(get_ledger_store)) -> RunListOut:
    return RunListOut(run_ids=store.list_run_ids())


@router.get("/{run_id}/trades", response_model=list[LedgerEntryOut])
def get_trades(
    run_id: str, store: LedgerStore = Depends(get_ledger_store)
) -> list[LedgerEntryOut]:
    return _entries_or_404(run_id, store)


@router.get("/{run_id}/metrics", response_model=PerformanceReportOut)
def get_metrics(
    run_id: str, store: LedgerStore = Depends(get_ledger_store)
) -> PerformanceReportOut:
    entries = _entries_or_404(run_id, store)
    # cash_after as an equity proxy — no persisted mark-to-market curve yet.
    equity_curve = [(e.fill_ts, e.cash_after) for e in entries]
    report = compute_metrics(equity_curve)
    return PerformanceReportOut(
        sharpe=report.sharpe,
        max_drawdown=report.max_drawdown,
        win_rate=report.win_rate,
        cagr=report.cagr,
    )
