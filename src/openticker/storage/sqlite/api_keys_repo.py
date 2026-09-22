"""REST API keys, stored as hashes only (ADR 17 in docs/adr)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import ApiKeyRow


class DuplicateApiKeyNameError(Exception):
    pass


@dataclass(frozen=True)
class StoredApiKey:
    id: int
    name: str
    prefix: str
    scope: str
    created_at: datetime  # tz-aware UTC
    revoked_at: datetime | None  # tz-aware UTC


def insert_api_key(
    name: str, key_hash: str, prefix: str, scope: str, now: datetime
) -> StoredApiKey:
    row = ApiKeyRow(
        name=name,
        key_hash=key_hash,
        prefix=prefix,
        scope=scope,
        created_at=_naive(now),
        revoked_at=None,
    )
    with Session(get_engine()) as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            raise DuplicateApiKeyNameError(f"an API key named {name!r} already exists") from exc
        return _stored(row)


def find_active_api_key(key_hash: str) -> StoredApiKey | None:
    statement = select(ApiKeyRow).where(
        ApiKeyRow.key_hash == key_hash, ApiKeyRow.revoked_at.is_(None)
    )
    with Session(get_engine()) as session:
        row = session.scalars(statement).one_or_none()
        return _stored(row) if row else None


def list_api_keys() -> list[StoredApiKey]:
    with Session(get_engine()) as session:
        rows = session.scalars(select(ApiKeyRow).order_by(ApiKeyRow.id)).all()
        return [_stored(row) for row in rows]


def revoke_api_key(name: str, now: datetime) -> bool:
    """False when no active key has that name."""
    statement = select(ApiKeyRow).where(ApiKeyRow.name == name, ApiKeyRow.revoked_at.is_(None))
    with Session(get_engine()) as session:
        row = session.scalars(statement).one_or_none()
        if row is None:
            return False
        row.revoked_at = _naive(now)
        session.commit()
        return True


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _stored(row: ApiKeyRow) -> StoredApiKey:
    return StoredApiKey(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scope=row.scope,
        created_at=row.created_at.replace(tzinfo=UTC),
        revoked_at=row.revoked_at.replace(tzinfo=UTC) if row.revoked_at else None,
    )
