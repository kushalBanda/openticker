from datetime import timedelta

from openticker.use_cases.api_keys import create_api_key, create_review_key, create_script_key
from tests.adapters.inbound.web.conftest import NOW, OWN, Web

ORDER = {
    "broker": "fake",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "side": "BUY",
    "quantity": 1,
    "product": "MIS",
}
SAME_ORIGIN = {"origin": OWN}
WEB_ONLY = [
    ("GET", "/api/v1/session"),
    ("POST", "/api/v1/session/sign-out"),
    ("POST", "/api/v1/session/sign-out-all"),
    ("GET", "/api/v1/brokers/fake/session"),
    ("DELETE", "/api/v1/brokers/fake/session"),
    ("GET", "/api/v1/instruments/status"),
    ("GET", "/api/v1/keys"),
    ("POST", "/api/v1/keys"),
    ("DELETE", "/api/v1/keys/laptop"),
    ("GET", "/api/v1/account"),
    ("POST", "/api/v1/account/reset"),
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/today"),
    ("GET", "/api/v1/setup"),
]


def test_cookie_session_reaches_full_routes_as_ui(web: Web) -> None:
    client = web.sign_in()

    placed = client.post("/api/v1/orders", json=ORDER, headers=SAME_ORIGIN)
    book = client.get("/api/v1/orders", params={"broker": "fake"}).json()

    assert placed.status_code == 200, placed.text
    assert book["orders"][0]["triggered_by"] == "ui"


def test_no_cookie_and_no_key_is_told_how_to_sign_in(web: Web) -> None:
    response = web.client.get("/api/v1/funds", params={"broker": "fake"})

    assert response.status_code == 401
    assert "openticker-serve ui login" in response.json()["detail"]


def test_expired_cookie_401(web: Web) -> None:
    client = web.sign_in()
    web.clock.now = NOW + timedelta(days=31)

    assert client.get("/api/v1/funds", params={"broker": "fake"}).status_code == 401


def test_signed_out_cookie_401(web: Web) -> None:
    client = web.sign_in()

    assert client.post("/api/v1/session/sign-out", headers=SAME_ORIGIN).status_code == 204
    assert client.get("/api/v1/funds", params={"broker": "fake"}).status_code == 401


def test_sign_out_everywhere_ends_every_browser(web: Web) -> None:
    client = web.sign_in()
    other = dict(client.cookies)
    web.client.cookies.clear()
    web.sign_in()

    ended = client.post("/api/v1/session/sign-out-all", headers=SAME_ORIGIN)

    assert ended.json() == {"ended": 2}
    client.cookies.clear()
    client.cookies.update(other)
    assert client.get("/api/v1/funds", params={"broker": "fake"}).status_code == 401


def test_session_route_says_who_is_signed_in(web: Web) -> None:
    client = web.sign_in()

    session = client.get("/api/v1/session").json()

    assert session["signed_in_at"] == "2026-09-22T09:30:00+05:30"
    assert session["expires_at"] == "2026-10-22T09:30:00+05:30"


def test_foreign_host_refused_even_with_cookie(web: Web) -> None:
    client = web.sign_in()

    response = client.get(
        "/api/v1/funds", params={"broker": "fake"}, headers={"host": "evil.example:8750"}
    )

    assert response.status_code == 403


def test_post_with_foreign_or_no_origin_refused(web: Web) -> None:
    client = web.sign_in()

    foreign = client.post("/api/v1/orders", json=ORDER, headers={"origin": "http://evil.example"})
    missing = client.post("/api/v1/orders", json=ORDER)

    assert (foreign.status_code, missing.status_code) == (403, 403)
    assert client.get("/api/v1/orders", params={"broker": "fake"}).json()["orders"] == []


def test_api_key_still_works_without_cookie(web: Web) -> None:
    _, key = create_api_key("laptop", NOW)

    response = web.client.post("/api/v1/orders", json=ORDER, headers={"X-API-Key": key})

    assert response.status_code == 200
    assert response.json()["status"] == "FILLED"


def test_script_and_review_keys_refused_on_every_web_only_route(web: Web) -> None:
    keys = [create_script_key("scr_1", "run_1", NOW), create_review_key("stg_1", "job_1", NOW)]

    for key in keys:
        for method, path in WEB_ONLY:
            response = web.client.request(method, path, headers={"X-API-Key": key})
            assert response.status_code == 403, (key[:12], path)
