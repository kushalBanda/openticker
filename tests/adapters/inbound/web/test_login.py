from urllib.parse import urlsplit

from openticker.use_cases.web_sessions import create_sign_in_link
from tests.adapters.inbound.web.conftest import OWN, Web


def _path(link: str) -> str:
    parts = urlsplit(link)
    return f"{parts.path}?{parts.query}"


def test_login_sets_httponly_strict_cookie_and_redirects(web: Web) -> None:
    response = web.client.get(_path(create_sign_in_link(OWN, web.clock())), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("ot_session=")
    for part in ("HttpOnly", "SameSite=strict", "Path=/", "Max-Age=2592000"):
        assert part in cookie


def test_used_link_shows_expired_page(web: Web) -> None:
    path = _path(create_sign_in_link(OWN, web.clock()))
    web.client.get(path, follow_redirects=False)
    web.client.cookies.clear()

    again = web.client.get(path, follow_redirects=False)

    assert again.status_code == 400
    assert "text/html" in again.headers["content-type"]
    assert "openticker-serve ui login" in again.text
    assert "set-cookie" not in again.headers


def test_login_without_a_token_shows_expired_page(web: Web) -> None:
    response = web.client.get("/login", follow_redirects=False)

    assert response.status_code == 400
    assert "openticker-serve ui login" in response.text
