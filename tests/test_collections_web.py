import pytest

from app.db import connection
from app.lists import sources
from app.lists.sources import FetchedList, ListItem
from app.lists.store import list_lists
from app.plex import client as plex
from app.plex.client import Library, save_connection
from app.settings_store import get_setting
from app.web import collections, settings
from tests.fakes import FakeSection, FakeServer, title


@pytest.fixture
def server(app, monkeypatch):
    movies = FakeSection(1, "Movies", items=[title(1, "Dune", imdb="tt1"), title(2, "Heat", tmdb="949")])
    fake = FakeServer([movies])
    monkeypatch.setattr(plex, "get_server", lambda conn: fake)
    monkeypatch.setattr(plex, "cached_overview", lambda conn: ("Server", "1.0", [Library("1", "Movies", "movie", 2)]))
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
    fetched = FetchedList("Top movies", [
        ListItem("movie", "Heat", 1995, "949"), ListItem("movie", "Nope", imdb_id="tt404"), ListItem("movie", "Dune", imdb_id="tt1"),
    ])
    monkeypatch.setattr(collections, "fetch_list", lambda db, ref: fetched)
    return fake


def indexed(app, server):
    from app.plex.guid_index import ensure_index

    with connection(app.state.db_path) as conn:
        ensure_index(conn, server, server._sections[0])


FORM = {"url": "https://mdblist.com/lists/u/top-movies", "library_key": "1", "placement": "home", "max_items": "50"}


def test_empty_lists_page(client, server):
    assert "No list yet" in client.get("/collections/lists").text
    assert 'href="/collections"' in client.get("/").text


def test_preview(client, app, server):
    indexed(app, server)
    html = client.post("/collections/lists/preview", data=FORM).text
    assert "Top movies" in html and "Missing from Movies (1)" in html and "Nope" in html
    assert html.index("/library/metadata/2/thumb") < html.index("/library/metadata/1/thumb")
    one = client.post("/collections/lists/preview", data={**FORM, "max_items": "1"}).text
    assert "/library/metadata/1/thumb" not in one


def test_preview_errors(client, server):
    assert "Pick a list" in client.post("/collections/lists/preview", data={**FORM, "url": "https://x.test/"}).text
    assert "Pick a library" in client.post("/collections/lists/preview", data={**FORM, "library_key": ""}).text


def test_save_edit_delete(client, app, server):
    response = client.post("/collections/lists", data=FORM, follow_redirects=False)
    assert response.status_code == 303
    with connection(app.state.db_path) as conn:
        [saved] = list_lists(conn)
    assert (saved.name, saved.library_title, saved.max_items) == ("Top movies", "Movies", 50)
    assert "Top movies" in client.get("/collections/lists").text

    client.post(f"/collections/lists/{saved.id}", data={**FORM, "name": "Mine", "placement": "library"})
    with connection(app.state.db_path) as conn:
        [edited] = list_lists(conn)
    assert (edited.name, edited.placement) == ("Mine", "library")

    client.post(f"/collections/lists/{saved.id}/delete")
    with connection(app.state.db_path) as conn:
        assert list_lists(conn) == []


def test_tmdb_settings(client, app, monkeypatch):
    monkeypatch.setattr(settings, "check_tmdb_key", lambda c, key: None if key == "good" else "TMDB refused the API key.")
    assert "refused" in client.post("/settings/tmdb", data={"key": "bad"}).text
    assert "Saved" in client.post("/settings/tmdb", data={"key": "good"}).text
    assert "Saved" in client.post("/settings/tmdb", data={"key": ""}).text  # keeps the saved key
    with connection(app.state.db_path) as conn:
        assert get_setting(conn, "tmdb.key") == "good"
    assert "Leave empty to keep it" in client.get("/settings/tmdb").text


def test_preview_waits_for_first_index(client, app, server, monkeypatch):
    from app.plex import guid_index

    started = []
    monkeypatch.setattr(guid_index, "_build_in_background", lambda *a: started.append(a))
    html = client.post("/collections/lists/preview", data=FORM).text
    assert "Indexing Movies" in html and 'hx-trigger="load delay:3s"' in html and started


def test_picked_source_makes_the_list(client, app, server, monkeypatch):
    def save(**fields):
        data = {"name": "L", "library_key": "1", "placement": "library", "max_items": "5", **fields}
        assert client.post("/collections/lists", data=data, follow_redirects=False).status_code == 303
        with connection(app.state.db_path) as conn:
            return conn.execute("SELECT url FROM lists ORDER BY id DESC").fetchone()[0]

    assert save(source="mdblist", mdblist_list="42", mdblist_url="") == "mdblist:42"
    assert save(source="mdblist", mdblist_url="https://mdblist.com/lists/u/top") == "https://mdblist.com/lists/u/top"
    assert save(source="tmdb", tmdb_preset="movie/popular", mdblist_list="42") == "tmdb:movie/popular"
    manifest = "https://addon.test/c0nf1gT0ken/manifest.json"
    assert save(source="stremio", stremio_manifest=manifest, stremio_catalog="series/nfx") == f"{manifest}#series/nfx"

    # The form hides the addon's configuration and saving it as shown keeps it.
    with connection(app.state.db_path) as conn:
        list_id = conn.execute("SELECT MAX(id) FROM lists").fetchone()[0]
    edit = client.get(f"/collections/lists/{list_id}").text
    assert "c0nf1gT0ken" not in edit and "https://addon.test/***/manifest.json" in edit
    client.post(f"/collections/lists/{list_id}", data={
        "editing_id": str(list_id), "source": "stremio", "stremio_manifest": "https://addon.test/***/manifest.json",
        "stremio_catalog": "movie/nfx", "name": "L", "library_key": "1", "placement": "library", "max_items": "5"})
    with connection(app.state.db_path) as conn:
        assert conn.execute("SELECT url FROM lists WHERE id = ?", (list_id,)).fetchone()[0] == f"{manifest}#movie/nfx"

    monkeypatch.setattr(sources, "stremio_catalogs", lambda client, url: [("movie/nfx", "Netflix")])
    html = client.post("/collections/stremio/catalogs", data={"editing_id": str(list_id), "source": "stremio",
                       "stremio_manifest": "https://addon.test/***/manifest.json", "stremio_catalog": "movie/nfx"}).text
    assert 'value="movie/nfx" data-name="Netflix" selected' in html
