from pydantic import BaseModel


class PositionOut(BaseModel):
    symbol: str
    quantity: int
    cash_after: float


class PositionListOut(BaseModel):
    run_id: str
    positions: list[PositionOut]
