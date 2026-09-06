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


class SmaCrossRequest(BacktestRequestBase):
    strategy_name: Literal["sma_cross"] = "sma_cross"
    long_window: int
    quantity: int


class BuyAndHoldRequest(BacktestRequestBase):
    strategy_name: Literal["buy_and_hold"] = "buy_and_hold"
    quantity: int


class MeanReversionRequest(BacktestRequestBase):
    strategy_name: Literal["mean_reversion"] = "mean_reversion"
    bb_window: int
    bb_std: float
    rsi_period: int
    rsi_buy_threshold: float
    rsi_sell_threshold: float
    quantity: int


class TimeSeriesMomentumRequest(BacktestRequestBase):
    strategy_name: Literal["time_series_momentum"] = "time_series_momentum"
    window: int
    target_risk_pct: float
    vol_window: int


class PairsTradingRequest(BacktestRequestBase):
    strategy_name: Literal["pairs_trading"] = "pairs_trading"
    formation_months: int
    trading_months: int
    top_n_pairs: int
    entry_z: float


# Add each new strategy's request model here as another Annotated union
# member, pydantic/FastAPI dispatches on strategy_name (the discriminator).
BacktestRequest = Annotated[
    SmaCrossRequest
    | BuyAndHoldRequest
    | MeanReversionRequest
    | TimeSeriesMomentumRequest
    | PairsTradingRequest,
    Field(discriminator="strategy_name"),
]


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
    total: int
    page: int
    page_size: int
    pages: int


class TradeListOut(BaseModel):
    trades: list[LedgerEntryOut]
    total: int
    page: int
    page_size: int
    pages: int


class PerformanceReportOut(BaseModel):
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    exponential_std: float
    win_rate: float
