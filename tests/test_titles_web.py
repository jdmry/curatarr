from types import SimpleNamespace

import pytest

from app.db import connection
from app.plex import client as plex
from app.plex.client import save_connection
from app.posters import fetch
from app.posters.fetch import FetchResult
from app.posters.sources import PosterSource, save_source
from app.scope import ScopeEntry
from app.sync.engine import source_for
from tests.fakes import FakeSection, FakeServer, title


@pytest.fixture
def server(app, monkeypatch):
    dune = title(1, "Dune", imdb="tt1")
    dune.librarySectionID, dune.librarySectionTitle = 1, "Movies"
    movies = FakeSection(1, "Movies", items=[dune, title(2, "No ids")])
    movies.search = lambda title=None, maxresults=None, **kw: [i for i in movies.items if title.lower() in i.title.lower()]
    fake = FakeServer([movies])
    monkeypatch.setattr(plex, "get_server", lambda conn: fake)
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
        save_source(conn, PosterSource(None, "PP", "https://p.test/{imdb_id}.jpg?access_key=s3cret"))
    monkeypatch.setattr(fetch, "fetch_poster", lambda *a: FetchResult(True, content=b"WEBP", content_type="image/webp"))
    return fake


def test_search_links_to_title(client, server):
    html = client.get("/posters/titles/search?q=dun").text
    assert 'hx-get="/posters/titles/1"' in html and "Dune" in html
    assert "Manual" in client.get("/posters/titles").text


def test_preview_then_apply(client, app, server):
    html = client.get("/posters/titles/1").text
    assert "Apply to Plex" in html and "data:image/webp;base64," in html and "s3cret" not in html
    dune = server._sections[0].items[0]
    assert dune.uploads == []

    with connection(app.state.db_path) as conn:
        source_id = conn.execute("SELECT id FROM poster_sources").fetchone()[0]
    html = client.post("/posters/titles/1/apply", data={"source_id": str(source_id)}).text
    assert "Poster sent to Plex" in html and dune.uploads == [b"WEBP"]
    with connection(app.state.db_path) as conn:
        assert conn.execute("SELECT rating_key FROM poster_state").fetchall()[0][0] == "1"
    assert "Sent" in client.get("/posters/titles/1").text


def test_title_without_ids_is_not_applied(client, server):
    html = client.get("/posters/titles/2").text
    assert "No poster" in html and "Apply to Plex" not in html


def test_source_for_follows_scope():
    a, b, default = (PosterSource(i, n, "https://x.test/{imdb_id}") for i, n in ((1, "A"), (2, "B"), (3, "D")))
    item = SimpleNamespace(librarySectionID=1, collections=[SimpleNamespace(tag="Marvel")])
    sources = {1: a, 2: b}
    library = ScopeEntry("1", "Movies", source_id=1)
    marvel = ScopeEntry("1", "Movies", "10", "Marvel", source_id=2)
    assert source_for(item, [library, marvel], sources, default) is b
    assert source_for(item, [library], sources, default) is a
    assert source_for(item, [ScopeEntry("1", "Movies")], sources, default) is default
    assert source_for(item, [ScopeEntry("9", "Other", source_id=1)], sources, default) is default
