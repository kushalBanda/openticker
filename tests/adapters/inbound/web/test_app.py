import shutil

from tests.adapters.inbound.web.conftest import Web

HTML = {"accept": "text/html,application/xhtml+xml"}


def test_index_served_for_app_routes(web: Web) -> None:
    for path in ("/", "/positions", "/strategies/stg_1"):
        response = web.client.get(path, headers=HTML)
        assert response.status_code == 200, path
        assert "OpenTicker" in response.text
        assert response.headers["cache-control"] == "no-cache"


def test_assets_cached_immutable(web: Web) -> None:
    response = web.client.get("/assets/app-3f9a.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_missing_asset_is_404_not_the_app(web: Web) -> None:
    assert web.client.get("/assets/gone-1234.js").status_code == 404


def test_unbuilt_page_when_dist_missing(web: Web) -> None:
    shutil.rmtree(web.dist)

    response = web.client.get("/", headers=HTML)

    assert response.status_code == 503
    assert "pnpm build" in response.text


def test_api_404_stays_json(web: Web) -> None:
    client = web.sign_in()

    response = client.get("/api/v1/nope", headers=HTML)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_health_still_open(web: Web) -> None:
    assert web.client.get("/health").json()["status"] == "ok"
