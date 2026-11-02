from types import SimpleNamespace

import pytest

from app.db import connection
from app.plex import client as plex
from app.plex.client import save_connection
from app.posters import fetch
from app.posters.fetch import FetchResult
from app.posters.sources import get_source, list_sources
from tests.fakes import FakeItem, guid, media, video

PP_URL = "https://pp.example.com/poster?tmdb_id={tmdb_id?}&imdb_id={imdb_id?}&type={type}&pc=stremio_tv_nuvio&access_key=k3y"


def sources(app):
    with connection(app.state.db_path) as conn:
        return list_sources(conn)


def create(client, url=PP_URL, **extra):
    return client.post("/settings/services", data={"url": url, "read_quality": "1", **extra}, follow_redirects=False)


def test_empty_state(client):
    assert "No poster service yet" in client.get("/settings/services").text


def test_create_postersplus_source(client, app):
    response = create(client)
    assert response.status_code == 303
    [source] = sources(app)
    assert source.name == "PostersPlus" and source.kind == "postersplus" and source.no_quality == "NONE"
    assert source.is_default and "pc=plex" in source.url_template and "access_key=k3y" in source.url_template

    page = client.get("/settings/services").text
    assert "access_key=***" in page and "k3y" not in page
    edit = client.get(f"/settings/services/{source.id}").text
    assert "access_key=***" in edit and "k3y" not in edit


def test_update_keeps_masked_secret(client, app):
    create(client)
    [source] = sources(app)
    masked = source.masked_template.replace("tg=", "")
    response = client.post(f"/settings/services/{source.id}", data={"url": masked + "&tg=large", "name": "Mine"},
                           follow_redirects=False)
    assert response.status_code == 303
    [updated] = sources(app)
    assert updated.name == "Mine" and "access_key=k3y" in updated.url_template and updated.revision == 2


def test_invalid_url_rerenders_form(client, app):
    response = create(client, url="not a url")
    assert response.status_code == 200 and "must start with http" in response.text
    assert sources(app) == []


def test_analyze_partial(client):
    html = client.post("/settings/services/analyze", data={"url": PP_URL}).text
    assert "PostersPlus detected" in html and "Client set to Plex" in html and "access_key" in html


@pytest.fixture
def plex_item(app, monkeypatch):
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
    item = FakeItem(title="Dune", lite={
        "ratingKey": 42, "year": 2021, "thumb": "/library/metadata/42/thumb/1",
        "guids": [guid("imdb://tt1160419"), guid("tmdb://438631")],
        "media": [media("4k", streams=[video(DOVIPresent=True)])],
    })
    server = SimpleNamespace(fetchItem=lambda key: item)
    monkeypatch.setattr(plex, "get_server", lambda conn: server)
    return item


def test_preview_with_unsaved_form(client, plex_item, monkeypatch):
    calls = []

    def fake_fetch(url, headers, timeout, secrets):
        calls.append(url)
        return FetchResult(True, b"\x89PNG", "image/png", 200, elapsed=1.2)

    monkeypatch.setattr(fetch, "fetch_poster", fake_fetch)
    html = client.post("/settings/services/test", data={"url": PP_URL, "rating_key": "42", "read_quality": "1"}).text
    assert calls == ["https://pp.example.com/poster?tmdb_id=438631&imdb_id=tt1160419&type=movie"
                     "&access_key=k3y&pc=plex&quality=4K,DV"]
    assert "data:image/png;base64," in html
    assert "access_key=***" in html and "k3y" not in html
    assert "Dune" in html and "DV" in html


def test_preview_saved_source_with_masked_secret(client, app, plex_item, monkeypatch):
    create(client)
    [source] = sources(app)
    calls = []
    monkeypatch.setattr(fetch, "fetch_poster", lambda url, *a: calls.append(url) or FetchResult(False, error="HTTP 500"))
    html = client.post("/settings/services/test", data={"url": source.masked_template, "editing_id": source.id,
                                              "rating_key": "42"}).text
    assert "access_key=k3y" in calls[0]
    assert "HTTP 500" in html


def test_preview_skipped_title(client, plex_item, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_poster", lambda *a: pytest.fail("should not fetch"))
    plex_item.guids = [guid("tmdb://438631")]
    html = client.post("/settings/services/test", data={"url": "https://x.test/{imdb_id}.jpg", "rating_key": "42"}).text
    assert "Skipped" in html and "imdb_id" in html


def test_default_and_delete(client, app):
    create(client)
    create(client, url="https://btttr.cc/poster/imdb/poster-default/{imdb_id}.jpg?rs=LB")
    first, second = sorted(sources(app), key=lambda s: s.id)
    client.post(f"/settings/services/{second.id}/default")
    with connection(app.state.db_path) as conn:
        assert get_source(conn, second.id).is_default
    client.post(f"/settings/services/{second.id}/delete")
    assert [s.id for s in sources(app)] == [first.id] and sources(app)[0].is_default


def test_title_search(client, app, monkeypatch):
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
    dune = SimpleNamespace(ratingKey=42, title="Dune", year=2021, TYPE="movie", thumb="/library/metadata/42/thumb/1")
    section = SimpleNamespace(type="movie", title="Films", search=lambda title, maxresults: [dune])
    music = SimpleNamespace(type="artist", title="Music", search=lambda **kw: pytest.fail("music searched"))
    server = SimpleNamespace(library=SimpleNamespace(sections=lambda: [section, music]))
    monkeypatch.setattr(plex, "get_server", lambda conn: server)

    html = client.get("/settings/services/titles", params={"q": "dune"}).text
    assert "Dune" in html and "2021 · Films" in html and '"rating_key": "42"' in html
    assert "Pick a movie" in client.get("/settings/services/titles", params={"q": "d"}).text


def test_preview_without_quality(client, plex_item, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch, "fetch_poster", lambda url, *a: calls.append(url) or FetchResult(False, error="x"))
    plex_item.reload = lambda: pytest.fail("quality should not be read")
    html = client.post("/settings/services/test", data={"url": PP_URL, "rating_key": "42"}).text
    assert calls[0].endswith("quality=NONE") and "not read" in html


RPDB_FORM = {"kind": "rpdb", "rpdb_key": "t1-s3cretkey", "rpdb_style": "poster-rt", "rpdb_lang": "fr",
             "rpdb_size": "medium", "rpdb_fallback": "1"}


def test_add_asks_which_service(client):
    html = client.get("/settings/services/new").text
    assert all(f"/settings/services/new?kind={k}" in html for k in ("postersplus", "rpdb", "generic"))
    rpdb_form = client.get("/settings/services/new?kind=rpdb").text
    assert 'name="rpdb_key"' in rpdb_form and 'name="rpdb_fallback" value="1" checked' in rpdb_form
    pp = client.get("/settings/services/new?kind=postersplus").text
    assert "PostersPlus URL" in pp and 'name="rpdb_key"' not in pp


def test_rpdb_source_builds_url_and_hides_key(client, app, plex_item, monkeypatch):
    assert "Enter your RPDB API key" in client.post("/settings/services", data={**RPDB_FORM, "rpdb_key": ""}).text
    assert create(client, url="", **RPDB_FORM).status_code == 303
    [source] = sources(app)
    assert source.kind == "rpdb" and source.name == "RPDB"
    assert source.url_template == ("https://api.ratingposterdb.com/t1-s3cretkey/imdb/poster-rt/{imdb_id}.jpg"
                                   "?fallback=true&lang=fr")
    page = client.get("/settings/services").text
    assert "s3cret" not in page and "api.ratingposterdb.com/***/imdb" in page
    edit = client.get(f"/settings/services/{source.id}").text
    assert "s3cret" not in edit and 'value="poster-rt" selected' in edit

    # Saving the form as shown keeps the hidden key.
    client.post(f"/settings/services/{source.id}", data={**RPDB_FORM, "rpdb_key": "***", "rpdb_style": "poster-default"})
    [source] = sources(app)
    assert "/t1-s3cretkey/imdb/poster-default/" in source.url_template

    calls = []
    monkeypatch.setattr(fetch, "fetch_poster", lambda url, *a: calls.append(url) or FetchResult(True, b"img", "image/jpeg", 200))
    html = client.post("/settings/services/test", data={**RPDB_FORM, "rating_key": "42"}).text
    assert calls == ["https://api.ratingposterdb.com/t1-s3cretkey/imdb/poster-rt/tt1160419.jpg?fallback=true&lang=fr"]
    assert "s3cret" not in html
