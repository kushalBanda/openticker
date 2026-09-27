from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text

from openticker.storage.sqlite.engine import get_engine
from openticker.use_cases.web_sessions import (
    create_sign_in_link,
    redeem_sign_in_link,
    session_of,
    sign_out,
    sign_out_everywhere,
)

NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)
BASE = "http://127.0.0.1:8750"


def _token(link: str) -> str:
    return parse_qs(urlsplit(link).query)["token"][0]


def _signed_in(now: datetime = NOW) -> str:
    secret = redeem_sign_in_link(_token(create_sign_in_link(BASE, now)), "test", now)
    assert secret is not None
    return secret


def test_link_points_at_login_on_the_given_base() -> None:
    link = create_sign_in_link(BASE, NOW)

    assert link.startswith(f"{BASE}/login?token=")
    assert len(_token(link)) >= 40


def test_link_redeems_once() -> None:
    token = _token(create_sign_in_link(BASE, NOW))

    first = redeem_sign_in_link(token, "test", NOW)

    assert first is not None and session_of(first, NOW) is not None
    assert redeem_sign_in_link(token, "test", NOW) is None


def test_link_expires_after_10_minutes() -> None:
    token = _token(create_sign_in_link(BASE, NOW))

    assert redeem_sign_in_link(token, "test", NOW + timedelta(minutes=10)) is None


def test_unknown_link_refused() -> None:
    assert redeem_sign_in_link("not-a-token", "test", NOW) is None


def test_session_expires_after_30_idle_days() -> None:
    secret = _signed_in()

    assert session_of(secret, NOW + timedelta(days=29, hours=23)) is not None
    assert session_of(secret, NOW + timedelta(days=60)) is None


def test_use_renews_expiry() -> None:
    secret = _signed_in()

    session_of(secret, NOW + timedelta(days=20))

    assert session_of(secret, NOW + timedelta(days=45)) is not None


def test_touch_writes_at_most_once_a_minute() -> None:
    secret = _signed_in()

    session_of(secret, NOW + timedelta(seconds=30))
    within = session_of(secret, NOW + timedelta(seconds=59))
    later = session_of(secret, NOW + timedelta(seconds=61))

    assert within is not None and within.last_seen_at == NOW
    assert later is not None and later.last_seen_at == NOW + timedelta(seconds=61)


def test_first_visit_starts_at_sign_in_with_no_previous() -> None:
    session = session_of(_signed_in(), NOW)

    assert session is not None
    assert session.visit_started_at == NOW
    assert session.previous_visit_at is None


def test_new_visit_only_after_10_idle_minutes() -> None:
    secret = _signed_in()

    busy = session_of(secret, NOW + timedelta(minutes=9))
    back = session_of(secret, NOW + timedelta(minutes=30))

    assert busy is not None and busy.visit_started_at == NOW
    assert back is not None
    assert back.visit_started_at == NOW + timedelta(minutes=30)
    assert back.previous_visit_at == NOW + timedelta(minutes=9)  # when it was last here


def test_sign_out_ends_only_this_session() -> None:
    mine, other = _signed_in(), _signed_in()

    sign_out(mine, NOW)

    assert session_of(mine, NOW) is None
    assert session_of(other, NOW) is not None


def test_sign_out_everywhere_revokes_all() -> None:
    first, second = _signed_in(), _signed_in()

    assert sign_out_everywhere(NOW) == 2
    assert session_of(first, NOW) is None
    assert session_of(second, NOW) is None


def test_only_hashes_are_stored() -> None:
    link = create_sign_in_link(BASE, NOW)
    secret = redeem_sign_in_link(_token(link), "test", NOW)
    assert secret is not None

    with get_engine().connect() as connection:
        rows = [*connection.execute(text("SELECT * FROM ui_sign_in_links"))]
        rows += [*connection.execute(text("SELECT * FROM ui_sessions"))]
    stored = " ".join(str(value) for row in rows for value in row)
    assert _token(link) not in stored
    assert secret not in stored
