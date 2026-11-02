import pytest

from app.db import connection
from app.plex import client as plex
from app.plex.client import save_connection
from app.posters.sources import PosterSource, save_source
from app.scope import ScopeEntry, list_scope, set_scope_entry
from tests.fakes import FakeCollection, FakeSection, FakeServer, title


@pytest.fixture
def server(app, monkeypatch):
    movies = FakeSection(1, "Movies", items=[title(i, f"Movie {i}", imdb=f"tt{i}") for i in range(1, 6)])
    movies.items.append(title(99, "No imdb", tmdb="5"))
    shows = FakeSection(2, "Shows", type="show", items=[title(50, "Show", TYPE="show", imdb="tt50")])
    music = FakeSection(3, "Music", type="artist")
    collection = FakeCollection(10, "Marvel", movies.items[:2])
    movies._collections = [collection]
    fake = FakeServer([movies, shows, music], [collection])
    monkeypatch.setattr(plex, "connect", lambda conn: fake)
    monkeypatch.setattr(plex, "get_server", lambda conn: fake)
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
    return fake


def add_source(app):
    with connection(app.state.db_path) as conn:
        return save_source(conn, PosterSource(None, "PP", "https://p.test/{imdb_id}.jpg?k=1"))


def test_scope_page_without_lists(client, server):
    html = client.get("/posters/scope").text
    assert "No collection yet" in html and "Add a poster service" in html


def run_test(client, app, mode="test", **data):
    client.post(f"/sync/{mode}", data=data)
    app.state.runner.wait(10)
    with connection(app.state.db_path) as conn:
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchone()
        items = conn.execute("SELECT * FROM run_items WHERE run_id = ? ORDER BY position", (run["id"],)).fetchall()
    return run, items


def test_test_sync_needs_scope(client, app, server):
    add_source(app)
    run, items = run_test(client, app)
    assert run["status"] == "failed" and "Collections" in run["error"]


def test_test_sync_runs(client, app, server):
    add_source(app)
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Movies"), True)
    run, items = run_test(client, app, max_items="0")
    assert run["status"] == "done" and run["mode"] == "test"
    assert (run["total"], run["applied"], run["skipped"], run["errors"]) == (6, 5, 1, 0)
    assert items[0]["url"] == "https://p.test/tt1.jpg?k=1" and items[0]["action"] == "apply"
    assert items[-1]["action"] == "skipped"

    run, items = run_test(client, app, max_items="2")
    assert run["total"] == 2

    page = client.get(f"/posters/history/{run['id']}").text
    assert "Movie 1" in page and "Would update" in page
    assert "Movie 1" not in client.get(f"/posters/history/{run['id']}?action=skipped").text

    card = client.get("/sync/card").text
    assert "View results" in card and "Run test" in card and "Sync to Plex" in card
    assert any("Test sync done" in line.message for line in app.state.events.tail(50))


def test_live_sync_uploads_and_remembers(client, app, server, monkeypatch):
    from app.posters import fetch
    from app.posters.fetch import FetchResult

    add_source(app)
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Movies"), True)
    fetched = []

    def fake_fetch(url, *args):
        fetched.append(url)
        return FetchResult(True, content=b"RIFF....WEBP", content_type="image/webp", status=200, elapsed=0.1)

    monkeypatch.setattr(fetch, "fetch_poster", fake_fetch)
    run, items = run_test(client, app, mode="live", max_items="0")
    assert run["status"] == "done" and run["mode"] == "live"
    assert (run["total"], run["applied"], run["skipped"], run["errors"]) == (6, 5, 1, 0)
    movie = server._sections[0].items[0]
    assert movie.uploads == [b"RIFF....WEBP"]
    assert any("poster updated" in line.message for line in app.state.events.tail(50))

    # Nothing changed: the second sync sends nothing.
    fetched.clear()
    run, items = run_test(client, app, mode="live", max_items="0")
    assert (run["applied"], run["unchanged"], fetched) == (0, 5, [])

    # Fix Match in Plex unlocked one poster: only that one is sent again.
    movie.fields = []
    run, items = run_test(client, app, mode="live", max_items="0")
    assert run["applied"] == 1 and len(movie.uploads) == 2


def test_live_sync_upload_error(client, app, server, monkeypatch):
    from app.posters import fetch
    from app.posters.fetch import FetchResult

    add_source(app)
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("2", "Shows"), True)
    monkeypatch.setattr(fetch, "fetch_poster", lambda *a: FetchResult(True, content=b"img", status=200))
    show = server._sections[1].items[0]
    show.uploadPoster = lambda **kw: (_ for _ in ()).throw(RuntimeError("(400) bad_request"))
    run, items = run_test(client, app, mode="live")
    assert run["errors"] == 1 and "Upload to Plex failed" in items[0]["reason"]
    with connection(app.state.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM poster_state").fetchone()[0] == 0


def test_schedule_card(client, app):
    html = client.get("/sync/schedule").text
    assert "Paused" in html and "Turn on" in html
    html = client.post("/sync/schedule", data={"enabled": "1", "every_hours": "3"}).text
    assert "Every 3 h" in html and "Next sync in 2 h 59 min" in html and "Pause" in html
    html = client.post("/sync/schedule", data={"enabled": "", "every_hours": "3"}).text
    assert "Paused" in html and 'value="3" selected' in html


def test_activity_stream_starts_after_rendered_lines(client, app):
    """Otherwise the stream replays every line already in the page."""
    app.state.events.info("one")
    app.state.events.info("two")
    last = app.state.events.tail(1)[0].id
    assert f'sse-connect="/events/logs?after={last}"' in client.get("/posters/sync").text


def test_sync_of_some_collections_only(client, app, server):
    add_source(app)
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Movies"), True)
    app.state.runner.start("test", only=[ScopeEntry("1", "Movies", "10", "Marvel")])
    app.state.runner.wait(10)
    with connection(app.state.db_path) as conn:
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchone()
    assert run["status"] == "done" and run["total"] == 2
    assert any("titles of Marvel" in line.message for line in app.state.events.tail(10))


def test_title_is_tried_again_once_when_plex_times_out(client, app, server, monkeypatch):
    import requests

    from app.sync import runner

    add_source(app)
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Movies"), True)
    calls = {}
    real = runner.evaluate

    def slow_plex(target, previous=None):
        title = target.item.title
        calls[title] = calls.get(title, 0) + 1
        if title == "Movie 2" or (title == "Movie 1" and calls[title] == 1):
            raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=15)")
        return real(target, previous)

    monkeypatch.setattr(runner, "evaluate", slow_plex)
    run, items = run_test(client, app, max_items="0")
    assert (run["applied"], run["errors"]) == (4, 1) and calls["Movie 1"] == 2 and calls["Movie 2"] == 2
    assert any(line.message == "Movie 2: Plex did not answer within 15 s, the next sync will try again"
               for line in app.state.events.tail(20))

