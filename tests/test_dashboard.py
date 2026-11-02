from types import SimpleNamespace

import pytest

from app.db import connection
from app.plex import client as plex
from app.plex.client import Library, save_connection
from app.posters.sources import PosterSource, save_source
from app.scope import ScopeEntry, set_scope_entry


@pytest.fixture
def configured(app):
    plex.forget_overview()
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
    yield
    plex.forget_overview()


def test_dashboard_page(client, configured):
    response = client.get("/")
    assert response.status_code == 200
    assert 'hx-get="/dashboard/recap"' in response.text
    assert "Connect your Plex server" not in response.text


def test_recap(client, app, configured, monkeypatch):
    server = SimpleNamespace(friendlyName="Home", version="1.41.3.9314-a0bfb8370")
    calls = []
    monkeypatch.setattr(plex, "get_server", lambda conn: server)
    monkeypatch.setattr(plex, "library_sizes", lambda srv: calls.append(1) or [
        Library("1", "Films", "movie", 1200), Library("2", "Séries", "show", 80),
    ])
    with connection(app.state.db_path) as conn:
        save_source(conn, PosterSource(None, "PP", "https://p.test/{imdb_id}.jpg", read_quality=False))
        set_scope_entry(conn, ScopeEntry("1", "Films", "9", "Marvel"), True)

    html = client.get("/dashboard/recap").text
    assert "Home" in html and "1,280" in html and "1,200 movies · 80 shows" in html
    assert "Posters for" in html and "collection</div>" in html and "Never" in html
    assert "tok" not in html
    client.get("/dashboard/recap")
    assert calls == [1]  # second load served from the cache


def test_recap_unreachable(client, configured, monkeypatch):
    def fail(conn):
        raise ConnectionError("boom")

    monkeypatch.setattr(plex, "get_server", fail)
    html = client.get("/dashboard/recap").text
    assert "unreachable" in html and "Choose what to sync" in html


def test_posters_banners(client, app, configured):
    assert "Add a poster service" in client.get("/posters/sync").text
    with connection(app.state.db_path) as conn:
        save_source(conn, PosterSource(None, "PP", "https://p.test/{imdb_id}.jpg"))
    html = client.get("/posters/sync").text
    assert "Add a poster service" not in html and "Choose collections" in html
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Films", "9", "Marvel"), True)
    assert 'class="banner"' not in client.get("/posters/sync").text
    assert 'class="banner"' not in client.get("/posters/history").text


def test_posters_pages(client, app, configured):
    assert client.get("/posters", follow_redirects=False).headers["location"] == "/posters/sync"
    assert "No sync yet" in client.get("/posters/history").text
    with connection(app.state.db_path) as conn:
        conn.execute("INSERT INTO runs (mode, status, total) VALUES ('test', 'done', 12)")
    assert "#1" in client.get("/posters/history").text
