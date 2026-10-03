"""Browser sign-in links and sessions, stored as hashes only (ADR 31 in docs/adr)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import SignInLinkRow, WebSessionRow

_KEEP_LINKS = timedelta(days=1)


@dataclass(frozen=True)
class WebSession:
    id_hash: str
    created_at: datetime  # tz-aware UTC, as are the rest
    expires_at: datetime
    last_seen_at: datetime
    visit_started_at: datetime | None
    previous_visit_at: datetime | None
    revoked_at: datetime | None
    user_agent: str | None


def insert_link(token_hash: str, now: datetime, expires_at: datetime) -> None:
    """Also deletes links more than a day old, used or not."""
    with Session(get_engine()) as session:
        session.execute(
            delete(SignInLinkRow).where(SignInLinkRow.created_at < _naive(now - _KEEP_LINKS))
        )
        session.add(
            SignInLinkRow(
                token_hash=token_hash,
                created_at=_naive(now),
                expires_at=_naive(expires_at),
                used_at=None,
            )
        )
        session.commit()


def redeem_link(token_hash: str, now: datetime) -> bool:
    """Marks an unused, unexpired link used; False when there is none."""
    statement = (
        update(SignInLinkRow)
        .where(
            SignInLinkRow.token_hash == token_hash,
            SignInLinkRow.used_at.is_(None),
            SignInLinkRow.expires_at > _naive(now),
        )
        .values(used_at=_naive(now))
    )
    with Session(get_engine()) as session:
        redeemed = bool(session.execute(statement).rowcount == 1)  # type: ignore[attr-defined]
        session.commit()
        return redeemed


def insert_session(
    id_hash: str, now: datetime, expires_at: datetime, user_agent: str | None
) -> None:
    with Session(get_engine()) as session:
        session.add(
            WebSessionRow(
                id_hash=id_hash,
                created_at=_naive(now),
                expires_at=_naive(expires_at),
                last_seen_at=_naive(now),
                visit_started_at=_naive(now),
                previous_visit_at=None,
                revoked_at=None,
                user_agent=user_agent,
            )
        )
        session.commit()


def find_session(id_hash: str) -> WebSession | None:
    with Session(get_engine()) as session:
        row = session.get(WebSessionRow, id_hash)
        return _stored(row) if row else None


def touch_session(id_hash: str, now: datetime, expires_at: datetime, new_visit: bool) -> None:
    """Records a use. A new visit keeps when the browser was last here, the
    end of the visit before: "since you were here" counts from it (ADR 34)."""
    with Session(get_engine()) as session:
        row = session.get(WebSessionRow, id_hash)
        if row is None:
            return
        if new_visit:
            row.previous_visit_at = row.last_seen_at
            row.visit_started_at = _naive(now)
        row.last_seen_at = _naive(now)
        row.expires_at = _naive(expires_at)
        session.commit()


def revoke_session(id_hash: str, now: datetime) -> None:
    with Session(get_engine()) as session:
        session.execute(
            update(WebSessionRow)
            .where(WebSessionRow.id_hash == id_hash, WebSessionRow.revoked_at.is_(None))
            .values(revoked_at=_naive(now))
        )
        session.commit()


def revoke_all_sessions(now: datetime) -> int:
    """How many live sessions were ended."""
    statement = (
        update(WebSessionRow)
        .where(WebSessionRow.revoked_at.is_(None), WebSessionRow.expires_at > _naive(now))
        .values(revoked_at=_naive(now))
    )
    with Session(get_engine()) as session:
        count: int = session.execute(statement).rowcount  # type: ignore[attr-defined]
        session.commit()
        return count


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment else None


def _stored(row: WebSessionRow) -> WebSession:
    return WebSession(
        id_hash=row.id_hash,
        created_at=row.created_at.replace(tzinfo=UTC),
        expires_at=row.expires_at.replace(tzinfo=UTC),
        last_seen_at=row.last_seen_at.replace(tzinfo=UTC),
        visit_started_at=_aware(row.visit_started_at),
        previous_visit_at=_aware(row.previous_visit_at),
        revoked_at=_aware(row.revoked_at),
        user_agent=row.user_agent,
    )
