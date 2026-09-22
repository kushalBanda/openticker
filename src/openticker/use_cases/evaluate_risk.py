"""Check a position's risk settings against the current price before acting
on them: the same rules a monitored position is held to (ADR 9 in docs/adr)."""

from dataclasses import dataclass

from openticker.core.risk.models import PositionRisk, RiskDecision
from openticker.core.risk.position import evaluate_position, validate_position
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Side
from openticker.use_cases.resolve_instrument import resolve_instrument


@dataclass(frozen=True)
class RiskCheck:
    last_price: float
    decision: RiskDecision
    warnings: list[str]  # settings that would exit at once or trail badly


def evaluate_risk(
    broker: BrokerPort,
    symbol: str,
    exchange: str,
    side: Side,
    quantity: int,
    entry_price: float | None,
    stop_loss: float | None,
    target: float | None,
    capital_cap: float | None,
) -> RiskCheck:
    """`entry_price` None means entering now, at the current price."""
    last_price = broker.get_quote(resolve_instrument(symbol, exchange)).last_price
    risk = PositionRisk(
        side=side,
        entry_price=entry_price if entry_price is not None else last_price,
        quantity=quantity,
        initial_sl=stop_loss,
        current_sl=stop_loss,
        target=target,
        highest_price=None,
        lowest_price=None,
        capital_cap=capital_cap,
    )
    return RiskCheck(
        last_price=last_price,
        decision=evaluate_position(risk, last_price),
        warnings=validate_position(risk, last_price),
    )
