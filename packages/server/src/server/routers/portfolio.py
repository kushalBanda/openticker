from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from strategy.storage.ledger_store import LedgerStore

from server.core.constants import API_PREFIX_PORTFOLIO
from server.core.deps import get_ledger_store
from server.schemas.portfolio import PositionListOut, PositionOut

router = APIRouter(prefix=API_PREFIX_PORTFOLIO, tags=["portfolio"])


@router.get("/{run_id}/positions", response_model=PositionListOut)
def get_positions(
    run_id: str, store: LedgerStore = Depends(get_ledger_store)
) -> PositionListOut:
    entries = store.query_entries(run_id)
    if not entries:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"no ledger entries for run_id {run_id!r}",
        )

    # entries are sequence-ordered; last entry per symbol carries the final
    # known position_after and cash_after for that run.
    latest_by_symbol = {e.symbol: e for e in entries}
    positions = [
        PositionOut(
            symbol=symbol,
            quantity=entry.position_after,
            cash_after=entry.cash_after,
        )
        for symbol, entry in latest_by_symbol.items()
    ]
    return PositionListOut(run_id=run_id, positions=positions)
