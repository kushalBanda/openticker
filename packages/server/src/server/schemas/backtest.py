from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BacktestRequestBase(BaseModel):
    symbols: list[str]
    interval: str = "1d"
    from_: Annotated[datetime, Field(alias="from")]
    to: datetime
    starting_cash: float = 100_000.0
    slippage_bps: float | None = None
    commission_per_share: float | None = None

    model_config = {"populate_by_name": True}


class SmaCrossoverRequest(BacktestRequestBase):
    strategy_name: Literal["sma_crossover"] = "sma_crossover"
    short_window: int
    long_window: int
    quantity: int


# Add each new strategy's request model here; once there are 2+, this
# becomes a discriminated union on strategy_name (pydantic requires 2+
# members for a discriminator).
BacktestRequest = SmaCrossoverRequest


class BacktestRunOut(BaseModel):
    run_id: str
    trade_count: int


class StrategyListOut(BaseModel):
    strategy_names: list[str]


class LedgerEntryOut(BaseModel):
    symbol: str
    side: str
    quantity: int
    fill_price: float
    fill_ts: datetime
    commission: float
    cost_basis_before: float
    realized_pnl: float
    cash_after: float
    position_after: int


class RunListOut(BaseModel):
    run_ids: list[str]


class PerformanceReportOut(BaseModel):
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    exponential_std: float
    win_rate: float
