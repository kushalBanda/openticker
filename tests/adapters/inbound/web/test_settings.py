"""The Settings page's routes (ADR 33 and ADR 37 in docs/adr), and the broker's
login redirect."""

from dataclasses import replace
from datetime import timedelta

from openticker.core.strategies.runs import Run, RunStatus
from openticker.ports.models import Credentials, Product
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.audit_repo import list_audit
from openticker.storage.sqlite.credentials_repo import get_credentials, save_credentials
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.api_keys import authenticate, create_script_key
from tests.adapters.inbound.web.conftest import NOW, OWN, Web
from tests.fixtures.strategies import STRADDLE

SAME_ORIGIN = {"origin": OWN}
ORDER = {
    "broker": "fake",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "side": "BUY",
    "quantity": 2,
    "product": "MIS",
}


def test_broker_session_says_connected_until_expiry_never_the_token(web: Web) -> None:
    client = web.sign_in()
    save_credentials(Credentials("fake", "secret-token", None, NOW + timedelta(hours=8)))

    body = client.get("/api/v1/brokers/fake/session").json()

    assert body["connected"] is True and body["stored"] is True
    assert body["expires_at"].startswith("2026-09-22T17:30:00+05:30")
    assert body["redirect_url"] == f"{OWN}/brokers/fake/callback"
    assert "secret-token" not in str(body)
    web.clock.now = NOW + timedelta(hours=9)
    assert client.get("/api/v1/brokers/fake/session").json()["connected"] is False


def test_unknown_broker_is_404(web: Web) -> None:
    assert web.sign_in().get("/api/v1/brokers/nope/session").status_code == 404


def test_disconnect_deletes_the_session_and_is_recorded(web: Web) -> None:
    client = web.sign_in()
    save_credentials(Credentials("fake", "t", None, None))

    response = client.delete("/api/v1/brokers/fake/session", headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert get_credentials("fake") is None
    [entry] = list_audit(1, "BrokerDisconnected")
    assert entry.triggered_by == "ui"


def test_callback_without_the_cookie_bounces_through_our_own_page(web: Web) -> None:
    response = web.client.get(
        "/brokers/fake/callback",
        params={"request_token": "abc", "status": "success"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert 'http-equiv="refresh"' in response.text
    assert "bounced=1" in response.text and "request_token=abc" in response.text
    assert get_credentials("fake") is None


def test_callback_still_without_a_session_asks_to_sign_in(web: Web) -> None:
    response = web.client.get(
        "/brokers/fake/callback",
        params={"request_token": "abc", "status": "success", "bounced": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "openticker-serve ui login" in response.text
    assert get_credentials("fake") is None


def test_callback_connects_and_goes_back_to_settings(web: Web) -> None:
    client = web.sign_in()

    response = client.get(
        "/brokers/fake/callback",
        params={"request_token": "abc", "status": "success"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?connected=fake"
    assert get_credentials("fake") is not None
    [entry] = list_audit(1, "BrokerConnected")
    assert entry.triggered_by == "ui"


def test_callback_that_failed_goes_back_with_why(web: Web) -> None:
    client = web.sign_in()

    response = client.get(
        "/brokers/fake/callback", params={"status": "cancelled"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/settings?connect_error=fake+login")
    assert get_credentials("fake") is None


def test_instruments_status_counts_each_exchange(web: Web) -> None:
    client = web.sign_in()
    client.post("/api/v1/instruments/sync", json={"broker": "fake"}, headers=SAME_ORIGIN)

    body = client.get("/api/v1/instruments/status").json()

    assert body["counts"] == {"NSE": 2}
    assert body["synced_at"] is not None


def test_a_key_is_shown_once_listed_without_it_and_revoked(web: Web) -> None:
    client = web.sign_in()
    create_script_key("scr_1", "run_1", NOW)

    created = client.post("/api/v1/keys", json={"name": "laptop"}, headers=SAME_ORIGIN)
    secret = created.json()["secret"]
    listed = client.get("/api/v1/keys").json()["keys"]

    assert created.status_code == 201 and authenticate(secret) is not None
    assert [(k["name"], k["managed"]) for k in listed] == [
        ("script-run_1", True),
        ("laptop", False),
    ]
    assert secret not in str(listed)
    assert client.delete("/api/v1/keys/laptop", headers=SAME_ORIGIN).status_code == 204
    assert authenticate(secret) is None
    assert client.delete("/api/v1/keys/script-run_1", headers=SAME_ORIGIN).status_code == 409
    assert client.delete("/api/v1/keys/laptop", headers=SAME_ORIGIN).status_code == 404


def test_bad_or_taken_key_names_are_refused(web: Web) -> None:
    client = web.sign_in()
    client.post("/api/v1/keys", json={"name": "laptop"}, headers=SAME_ORIGIN)

    taken = client.post("/api/v1/keys", json={"name": "laptop"}, headers=SAME_ORIGIN)
    bad = client.post("/api/v1/keys", json={"name": "My Laptop"}, headers=SAME_ORIGIN)

    assert (taken.status_code, bad.status_code) == (409, 422)


def test_account_shows_capital_leverage_and_charge_rates(web: Web) -> None:
    body = web.sign_in().get("/api/v1/account").json()

    assert body["starting_capital"] == 10_000_000.0
    assert body["capital_cap"] is None
    assert body["leverage"]["equity_intraday"] == 5.0
    assert body["charges_as_of"] and body["charges_source"]
    assert body["last_charge_check"] is None


def test_reset_refused_while_a_strategy_runs_then_succeeds(web: Web) -> None:
    client = web.sign_in()
    assert client.post("/api/v1/orders", json=ORDER, headers=SAME_ORIGIN).status_code == 200
    stored = insert_strategy("Short straddle", STRADDLE, NOW)
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id=stored.id,
        broker="fake",
        product=Product.MIS,
        status=RunStatus.OPEN,
        trigger="ui",
        started_at=NOW,
        legs=(),
    )
    with write_transaction() as session:
        runs_repo.insert_run(session, run)
    reset = {"confirm": "RESET"}

    refused = client.post("/api/v1/account/reset", json=reset, headers=SAME_ORIGIN)
    assert refused.status_code == 409
    assert "Short straddle" in refused.json()["detail"]
    assert client.get("/api/v1/positions", params={"broker": "fake"}).json()["positions"]

    runs_repo.save_run(replace(run, status=RunStatus.ENDED))
    done = client.post("/api/v1/account/reset", json=reset, headers=SAME_ORIGIN)

    assert done.status_code == 200, done.text
    assert done.json()["positions"] == 1
    assert client.get("/api/v1/positions", params={"broker": "fake"}).json()["positions"] == []
    [entry] = list_audit(1, "PaperAccountReset")
    assert entry.triggered_by == "ui"


def test_reset_needs_the_word(web: Web) -> None:
    response = web.sign_in().post(
        "/api/v1/account/reset", json={"confirm": "yes"}, headers=SAME_ORIGIN
    )

    assert response.status_code == 422
    assert "type RESET" in response.json()["detail"]


def test_notifications_say_on_or_off_only(web: Web) -> None:
    assert web.sign_in().get("/api/v1/notifications").json() == {"slack": False, "email": False}
