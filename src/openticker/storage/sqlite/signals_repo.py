"""Signal strategies' alert URLs, and the calls made to them (ADR 24 in
docs/adr). Only a token's hash is stored."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import StrategySignalRow, StrategyWebhookRow


@dataclass(frozen=True)
class StoredWebhook:
    strategy_id: str
    broker: str
    allowed_ips: tuple[str, ...]  # addresses and CIDR ranges; empty allows any
    created_at: datetime  # tz-aware UTC


@dataclass(frozen=True)
class SignalCall:
    id: int
    strategy_id: str
    received_at: datetime  # tz-aware UTC
    client_ip: str | None
    result: str
    message: str
    alert_format: str | None
    payload: str | None
    command_ids: tuple[int, ...]


def set_webhook(
    session: Session,
    strategy_id: str,
    token_hash: str,
    broker: str,
    allowed_ips: tuple[str, ...],
    now: datetime,
) -> StoredWebhook:
    """Replaces any URL the strategy had: the old token stops working."""
    session.execute(delete(StrategyWebhookRow).where(StrategyWebhookRow.strategy_id == strategy_id))
    row = StrategyWebhookRow(
        strategy_id=strategy_id,
        token_hash=token_hash,
        broker=broker,
        allowed_ips=json.dumps(list(allowed_ips)),
        created_at=_naive(now),
    )
    session.add(row)
    session.flush()
    return _webhook(row)


def remove_webhook(session: Session, strategy_id: str) -> bool:
    result = session.execute(
        delete(StrategyWebhookRow).where(StrategyWebhookRow.strategy_id == strategy_id)
    )
    return bool(getattr(result, "rowcount", 0))


def find_webhook(strategy_id: str) -> StoredWebhook | None:
    with Session(get_engine()) as session:
        row = session.get(StrategyWebhookRow, strategy_id)
        return _webhook(row) if row else None


def webhook_by_hash(token_hash: str) -> StoredWebhook | None:
    statement = select(StrategyWebhookRow).where(StrategyWebhookRow.token_hash == token_hash)
    with Session(get_engine()) as session:
        row = session.scalars(statement).one_or_none()
        return _webhook(row) if row else None


def record_call(
    strategy_id: str,
    now: datetime,
    client_ip: str | None,
    result: str,
    message: str,
    alert_format: str | None = None,
    payload: str | None = None,
    command_ids: tuple[int, ...] = (),
) -> int:
    with Session(get_engine()) as session:
        row = StrategySignalRow(
            strategy_id=strategy_id,
            received_at=_naive(now),
            client_ip=client_ip,
            result=result,
            message=message,
            alert_format=alert_format,
            payload=payload,
            command_ids=json.dumps(list(command_ids)) if command_ids else None,
        )
        session.add(row)
        session.commit()
        return row.id


def calls_since(strategy_id: str, since: datetime) -> int:
    statement = select(func.count(StrategySignalRow.id)).where(
        StrategySignalRow.strategy_id == strategy_id,
        StrategySignalRow.received_at >= _naive(since),
    )
    with Session(get_engine()) as session:
        return int(session.scalar(statement) or 0)


def list_calls(strategy_id: str, limit: int) -> list[SignalCall]:
    """Newest first."""
    statement = (
        select(StrategySignalRow)
        .where(StrategySignalRow.strategy_id == strategy_id)
        .order_by(StrategySignalRow.id.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [
            SignalCall(
                id=row.id,
                strategy_id=row.strategy_id,
                received_at=row.received_at.replace(tzinfo=UTC),
                client_ip=row.client_ip,
                result=row.result,
                message=row.message,
                alert_format=row.alert_format,
                payload=row.payload,
                command_ids=tuple(json.loads(row.command_ids)) if row.command_ids else (),
            )
            for row in session.scalars(statement).all()
        ]


def _webhook(row: StrategyWebhookRow) -> StoredWebhook:
    return StoredWebhook(
        strategy_id=row.strategy_id,
        broker=row.broker,
        allowed_ips=tuple(json.loads(row.allowed_ips)),
        created_at=row.created_at.replace(tzinfo=UTC),
    )


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)
