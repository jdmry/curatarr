import httpx

from app.db import connection
from app.plex.client import save_connection


def configure(app):
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")


def mock_plex(app, handler):
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_rejects_non_library_paths(client, app):
    configure(app)
    for path in ("/photo/:/transcode", "http://evil/x", "/library/../accounts"):
        assert client.get("/plex/image", params={"path": path}).status_code == 400


def test_requires_plex(client):
    assert client.get("/plex/image", params={"path": "/library/metadata/1/thumb/2"}).status_code == 404


def test_proxies_image_without_exposing_token(client, app):
    configure(app)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"JPEG", headers={"content-type": "image/jpeg"})

    mock_plex(app, handler)
    response = client.get("/plex/image", params={"path": "/library/metadata/1/thumb/2", "w": 5000})
    assert response.status_code == 200
    assert response.content == b"JPEG"
    assert "tok" not in str(response.headers)
    request = seen[0]
    assert request.headers["X-Plex-Token"] == "tok"
    assert "tok" not in str(request.url)
    assert request.url.params["url"] == "/library/metadata/1/thumb/2"
    assert request.url.params["width"] == "1000"


def test_plex_error_is_502(client, app):
    configure(app)
    mock_plex(app, lambda request: httpx.Response(401))
    assert client.get("/plex/image", params={"path": "/library/metadata/1/thumb/2"}).status_code == 502
