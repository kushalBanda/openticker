from http import HTTPStatus
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from ingest.core.engine import DataEngine
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from strategy.backtest.broker import BacktestBroker
from strategy.core.engine import BacktestEngine
from strategy.core.portfolio import Portfolio
from strategy.core.registry import StrategyFactory, list_strategy_names
from strategy.metrics.performance import compute_metrics
from strategy.storage.equity_curve_store import EquityCurveStore
from strategy.storage.ledger_store import LedgerStore

from server.core.constants import (
    API_PREFIX_BACKTEST,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
)
from server.core.deps import (
    get_data_engine,
    get_equity_curve_store,
    get_ledger_store,
    get_session,
)
from server.core.security import Session
from server.schemas.backtest import (
    BacktestRequest,
    BacktestRequestBase,
    BacktestRunOut,
    LedgerEntryOut,
    PerformanceReportOut,
    RunListOut,
    StrategyListOut,
    TradeListOut,
)

router = APIRouter(prefix=API_PREFIX_BACKTEST, tags=["backtests"])

# /strategies isn't under the /backtests prefix above (it lists strategy
# names, not runs) — mounted separately in app.py.
action_router = APIRouter(tags=["backtests"])


def _strategy_params(request: BacktestRequest) -> dict[str, object]:
    extra_fields = set(type(request).model_fields) - set(
        BacktestRequestBase.model_fields
    ) - {"strategy_name"}
    return request.model_dump(include=extra_fields)


async def _fetch_bars(
    request: BacktestRequest, engine: DataEngine, provider: str
) -> dict[str, list[Bar]]:
    bars: dict[str, list[Bar]] = {}
    for symbol in request.symbols:
        symbol_bars = await engine.fetch_historical(
            symbol, request.interval, request.from_, request.to, provider=provider
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


@router.post("", response_model=BacktestRunOut)
async def run_backtest(
    request: BacktestRequest,
    session: Session = Depends(get_session),
    data_engine: DataEngine = Depends(get_data_engine),
    ledger_store: LedgerStore = Depends(get_ledger_store),
    equity_curve_store: EquityCurveStore = Depends(get_equity_curve_store),
) -> BacktestRunOut:
    bars = await _fetch_bars(request, data_engine, session["provider"])
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
    equity_curve_store.write_points(run_id, portfolio.equity_curve)
    return BacktestRunOut(run_id=run_id, trade_count=len(portfolio.ledger.entries))


@action_router.get("/strategies", response_model=StrategyListOut)
def get_strategies() -> StrategyListOut:
    return StrategyListOut(strategy_names=list_strategy_names())


def _pages(total: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size if total else 0


@router.get("", response_model=RunListOut)
def list_runs(
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    store: LedgerStore = Depends(get_ledger_store),
) -> RunListOut:
    total = store.count_run_ids()
    run_ids = store.list_run_ids(limit=page_size, offset=(page - 1) * page_size)
    return RunListOut(
        run_ids=run_ids,
        total=total,
        page=page,
        page_size=page_size,
        pages=_pages(total, page_size),
    )


@router.get("/{run_id}/trades", response_model=TradeListOut)
def get_trades(
    run_id: str,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    store: LedgerStore = Depends(get_ledger_store),
) -> TradeListOut:
    total = store.count_entries(run_id)
    if not total:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"no ledger entries for run_id {run_id!r}",
        )
    entries = store.query_entries(
        run_id, limit=page_size, offset=(page - 1) * page_size
    )
    trades = [
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
    return TradeListOut(
        trades=trades,
        total=total,
        page=page,
        page_size=page_size,
        pages=_pages(total, page_size),
    )


@router.get("/{run_id}/metrics", response_model=PerformanceReportOut)
def get_metrics(
    run_id: str, store: EquityCurveStore = Depends(get_equity_curve_store)
) -> PerformanceReportOut:
    equity_curve = store.query_points(run_id)
    if not equity_curve:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"no equity curve for run_id {run_id!r}",
        )
    try:
        report = compute_metrics(equity_curve)
    except InsufficientDataError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=f"cannot compute metrics for run_id {run_id!r}: {exc}",
        ) from exc
    return PerformanceReportOut(
        total_return=report.total_return,
        annualized_return=report.annualized_return,
        max_drawdown=report.max_drawdown,
        sharpe_ratio=report.sharpe_ratio,
        exponential_std=report.exponential_std,
        win_rate=report.win_rate,
    )
