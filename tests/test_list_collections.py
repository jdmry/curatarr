import pytest

from app.db import connection
from app.lists import collections, sources
from app.lists.collections import LABEL, apply, plan
from app.lists.sources import FetchedList, ListItem
from app.lists.store import ListConfig, get_list, save_list
from app.plex.sharing import Friend
from app.plex import client as plex
from app.plex.client import save_connection
from app.plex.guid_index import ensure_index, forget_index
from app.posters.sources import PosterSource, save_source
from app.scope import ScopeEntry, list_scope, set_scope_entry
from tests.fakes import FakeCollection, FakeSection, FakeServer, title

MOVIES = [title(i, f"M{i}", imdb=f"tt{i}") for i in range(1, 7)]


def make_server():
    movies = FakeSection(1, "Movies", items=list(MOVIES))
    shows = FakeSection(2, "Shows", type="show", items=[title(50, "S", TYPE="show", imdb="tt50")])
    return FakeServer([movies, shows]), movies


def config(**kw):
    return ListConfig(**{"id": 1, "name": "Top", "url": "https://mdblist.com/lists/u/top", "library_key": "1",
                         "library_title": "Movies", **kw})


def keys(collection):
    return [str(i.ratingKey) for i in collection.items()]


def test_create_in_list_order_with_label_and_home():
    server, movies = make_server()
    wanted = [MOVIES[2], MOVIES[0], MOVIES[4]]
    steps = plan(None, config(), ["3", "1", "5"])
    assert steps.create and steps.describe(3) == "created with 3 titles"
    collection = apply(server, movies, None, config(), wanted, steps)
    assert keys(collection) == ["3", "1", "5"] and collection.labels == [LABEL] and collection.sort == "custom"
    assert collection.hub.updates == [(True, True, True)]


def test_update_adds_removes_reorders_renames():
    server, movies = make_server()
    collection = FakeCollection(10, "Old name", [MOVIES[0], MOVIES[1], MOVIES[2]], server=server)
    wanted = [MOVIES[2], MOVIES[3], MOVIES[0]]
    steps = plan(collection, config(), ["3", "4", "1"])
    assert (steps.add, steps.remove, steps.reorder, steps.rename) == (["4"], ["2"], True, True)
    assert steps.describe(3) == "1 added, 1 removed, reordered, renamed"
    apply(server, movies, collection, config(), wanted, steps)
    assert keys(collection) == ["3", "4", "1"] and collection.title == "Top"

    again = plan(collection, config(), ["3", "4", "1"])
    assert not again.changed and again.describe(3) == "unchanged"


def test_only_misplaced_items_move():
    server, movies = make_server()
    collection = FakeCollection(10, "Top", MOVIES[:5], server=server)
    apply(server, movies, collection, config(), [MOVIES[4]] + MOVIES[:4], plan(collection, config(), ["5", "1", "2", "3", "4"]))
    assert keys(collection) == ["5", "1", "2", "3", "4"] and collection.moves == 1


def test_empty_list_deletes_and_library_change_recreates():
    server, movies = make_server()
    collection = FakeCollection(10, "Top", MOVIES[:2], server=server)
    steps = plan(collection, config(), [])
    assert steps.delete and apply(server, movies, collection, config(), [], steps) is None and collection.deleted

    elsewhere = FakeCollection(11, "Top", [], section_key=2, server=server)
    steps = plan(elsewhere, config(), ["1"])
    assert steps.delete and steps.create
    new = apply(server, movies, elsewhere, config(), [MOVIES[0]], steps)
    assert elsewhere.deleted and new.librarySectionID == 1


def test_visibility_per_placement():
    server, movies = make_server()
    collection = FakeCollection(10, "Top", [MOVIES[0]], server=server)
    collections.set_visibility(collection, "library")
    assert collection.hub.updates == []  # never promoted: nothing to hide
    collections.set_visibility(collection, "recommended")
    collections.set_visibility(collection, "recommended")
    collections.set_visibility(collection, "library")
    assert collection.hub.updates == [(True, False, False), (False, False, False)]


@pytest.fixture
def plex_server(app, monkeypatch):
    server, movies = make_server()
    monkeypatch.setattr(plex, "connect", lambda conn: server)
    monkeypatch.setattr(plex, "get_server", lambda conn: server)
    items = [ListItem("movie", "M3", imdb_id="tt3"), ListItem("movie", "Gone", imdb_id="tt404"),
             ListItem("movie", "M1", imdb_id="tt1"), ListItem("movie", "M2", imdb_id="tt2")]
    monkeypatch.setattr(sources, "fetch", lambda ref, http, *keys, **kw: FetchedList("Top", items))
    with connection(app.state.db_path) as conn:
        save_connection(conn, "http://plex:32400", "tok")
        ensure_index(conn, server, movies)
        save_list(conn, config(id=None, max_items=2))
    return server


def run(client, app, mode, **data):
    client.post(f"/collections/sync/{mode}", data=data)
    app.state.list_runner.wait(10)
    with connection(app.state.db_path) as conn:
        return get_list(conn, 1)


def test_test_sync_writes_nothing(client, app, plex_server):
    saved = run(client, app, "test")
    assert saved.collection_key is None and plex_server._collections == {}
    assert app.state.list_runner.results == {1: "created with 2 titles"}
    assert "created with 2 titles" in client.get("/collections/panel").text


def test_live_sync_then_unchanged_then_delete(client, app, plex_server):
    saved = run(client, app, "live")
    collection = plex_server._collections[int(saved.collection_key)]
    assert keys(collection) == ["3", "1"] and (saved.last_total, saved.last_matched) == (4, 2)

    run(client, app, "live", list_id="1")
    assert app.state.list_runner.results == {1: "unchanged"}

    client.post("/collections/lists/1/delete")
    assert collection.deleted



def test_sync_reports_progress(client, app, plex_server):
    with connection(app.state.db_path) as conn:
        save_list(conn, config(id=None, name="Second", max_items=2))
        forget_index(conn, "1")
    run(client, app, "live")
    messages = [line.message for line in app.state.events.tail(30)]
    assert "Top (1 of 2): reading the list" in messages and "Second (2 of 2): reading the list" in messages
    assert any(message.startswith("Indexing Movies") for message in messages)
    assert "Top: creating the collection with 2 titles" in messages
    assert app.state.list_runner.progress is None


class FakePosters:
    def __init__(self):
        self.calls = []

    def start(self, mode, only=None):
        self.calls.append((mode, only))


def test_picked_collection_follows_its_list_and_gets_posters(client, app, plex_server):
    posters = app.state.list_runner.posters = FakePosters()
    saved = run(client, app, "live")
    assert posters.calls == []
    with connection(app.state.db_path) as conn:
        rpdb = save_source(conn, PosterSource(None, "RPDB", "https://r.test/{imdb_id}.jpg"))
        set_scope_entry(conn, ScopeEntry("1", "Movies", saved.collection_key, "Top", rpdb, True), True)
        save_list(conn, config(id=1, name="Renamed", max_items=2))

    run(client, app, "test")
    assert posters.calls == []
    assert any("posters would be synced" in line.message for line in app.state.events.tail(10))

    run(client, app, "live")
    entry = ScopeEntry("1", "Movies", saved.collection_key, "Renamed", rpdb, True)
    with connection(app.state.db_path) as conn:
        assert list_scope(conn) == [entry]
    assert posters.calls == [("live", [entry])]

    client.post("/collections/lists/1/delete")
    with connection(app.state.db_path) as conn:
        assert list_scope(conn) == []


def test_refresh_tick_only_for_list_collections(client, app, plex_server):
    saved = run(client, app, "live")
    data = {"library_key": "1", "library_title": "Movies", "collection_key": saved.collection_key,
            "collection_title": "Top", "enabled": "1", "refresh_posters": "1"}
    html = client.post("/posters/scope/entry", data={**data, "linked": "1"}).text
    assert "Sync posters on each collection sync" in html
    with connection(app.state.db_path) as conn:
        assert list_scope(conn)[0].refresh_posters
    client.post("/posters/scope/entry", data=data)
    with connection(app.state.db_path) as conn:
        assert not list_scope(conn)[0].refresh_posters

class FakeManagedHub:
    def __init__(self, hubs, identifier, title, home=False):
        self.hubs, self.identifier, self.title = hubs, identifier, title
        self.promotedToOwnHome = self.promotedToSharedHome = home
        self.promotedToRecommended = True

    def move(self, after=None):
        self.hubs.remove(self)
        self.hubs.insert(0 if after is None else self.hubs.index(after) + 1, self)


def test_order_moves_rows(client, app, plex_server):
    hubs = []
    hubs += [FakeManagedHub(hubs, "movie.recentlyadded", "Recently Added"),
             FakeManagedHub(hubs, "custom.collection.1.1000", "Top", home=True),
             FakeManagedHub(hubs, "movie.recentlyviewed", "Recently Watched")]
    plex_server._sections[0].managedHubs = lambda: list(hubs)
    with connection(app.state.db_path) as conn:
        conn.execute("UPDATE lists SET collection_key = '1000'")

    html = client.get("/collections/order/1").text
    assert html.index("Recently Added") < html.index("Top") and 'class="hub-row ours"' in html

    client.post("/collections/order/1/move", data={"identifier": "custom.collection.1.1000", "direction": "up"})
    assert [h.title for h in hubs] == ["Top", "Recently Added", "Recently Watched"]
    html = client.post("/collections/order/1/move", data={"identifier": "movie.recentlyadded", "direction": "down"}).text
    assert [h.title for h in hubs] == ["Top", "Recently Watched", "Recently Added"]
    assert html.index("Recently Watched") < html.index("Recently Added")
    client.post("/collections/order/1/move", data={"identifier": "movie.recentlyadded", "direction": "up"})
    assert [h.title for h in hubs] == ["Top", "Recently Added", "Recently Watched"]
    assert "Home order" in client.get("/collections/order").text


def test_in_plex_lists_every_collection_and_deletes_unmanaged_ones(client, app, plex_server):
    movies = plex_server._sections[0]
    ours = FakeCollection(1000, "Top", MOVIES[:2], server=plex_server)
    agregarr = FakeCollection(1001, "Trending", MOVIES[2:5], server=plex_server)
    agregarr.labels = ["Agregarrtmdb10090"]
    orphan = FakeCollection(1002, "Old Top", MOVIES[:1], server=plex_server)
    orphan.labels = [LABEL]
    for c in (ours, agregarr, orphan):
        plex_server._collections[c.ratingKey] = c
    movies._collections = [ours, agregarr, orphan]
    with connection(app.state.db_path) as conn:
        conn.execute("UPDATE lists SET collection_key = '1000'")

    assert "Clean up" in client.get("/collections/plex").text
    html = client.get("/collections/plex/1").text
    assert "Agregarr" in html and "3 titles" in html and f"{LABEL}, no list" in html
    assert html.count('hx-post="/collections/plex/1/delete"') == 2  # not the list's own collection
    assert 'href="/collections/lists/1"' in html

    html = client.post("/collections/plex/1/delete", data={"rating_key": "1000"}).text
    assert "delete the list instead" in html and not ours.deleted
    html = client.post("/collections/plex/1/delete", data={"rating_key": "1001"}).text
    assert agregarr.deleted and "Trending deleted" in html
    assert "already gone" in client.post("/collections/plex/1/delete", data={"rating_key": "1001"}).text
    assert "already gone" in client.post("/collections/plex/2/delete", data={"rating_key": "1002"}).text
    assert not orphan.deleted  # other library: refused
    assert any("Trending deleted" in line.message for line in app.state.events.tail(10))


def test_lists_schedule_card(client, app, plex_server):
    assert 'hx-get="/collections/schedule"' in client.get("/collections/lists").text
    html = client.post("/collections/schedule", data={"enabled": "1", "every_hours": "12"}).text
    assert "Every 12 h" in html and 'hx-post="/collections/schedule"' in html and "every list is synced" in html
    assert "Paused" in client.get("/sync/schedule").text  # posters schedule untouched


def test_private_list_hides_collection_from_other_friends(client, app, plex_server, monkeypatch):
    from app.plex import sharing

    people = [Friend("7", "bob", "Bob", {"filterMovies": "label!=AgregarrX", "filterTelevision": ""}),
              Friend("8", "eve", "Eve", {"filterMovies": "", "filterTelevision": ""})]
    updates = []
    monkeypatch.setattr(sharing, "friends", lambda *a: people)
    monkeypatch.setattr(sharing, "update", lambda http, token, cid, friend, filters: updates.append((friend.id, filters)))
    with connection(app.state.db_path) as conn:
        conn.execute("UPDATE lists SET audience = '7', audience_name = 'Bob'")

    run(client, app, "test")
    assert updates == [] and plex_server._collections == {}

    saved = run(client, app, "live")
    collection = plex_server._collections[int(saved.collection_key)]
    assert "curatarr-private-1" in collection.labels and collection.hub.updates == [(True, True, True)]
    assert updates == [("8", {"filterMovies": "label!=curatarr-private-1", "filterTelevision": "label!=curatarr-private-1"})]

    # Back to everyone: the label leaves the collection and Eve's restriction, Bob's own stays.
    people[1].settings = {"filterMovies": "label!=curatarr-private-1", "filterTelevision": "label!=curatarr-private-1"}
    updates.clear()
    with connection(app.state.db_path) as conn:
        conn.execute("UPDATE lists SET audience = 'all'")
    run(client, app, "live")
    assert "curatarr-private-1" not in collection.labels
    assert updates == [("8", {"filterMovies": "", "filterTelevision": ""})]


def test_owner_only_is_not_on_friends_home(client, app, plex_server, monkeypatch):
    from app.plex import sharing

    monkeypatch.setattr(sharing, "friends", lambda *a: [])
    with connection(app.state.db_path) as conn:
        conn.execute("UPDATE lists SET audience = 'owner'")
    saved = run(client, app, "live")
    assert plex_server._collections[int(saved.collection_key)].hub.updates == [(True, True, False)]


def test_form_lists_friends(client, app, plex_server, monkeypatch):
    from app.plex import sharing
    from app.web import collections as web

    monkeypatch.setattr(web, "_friends_cache", None)
    monkeypatch.setattr(sharing, "friends", lambda *a: [Friend("7", "bob", "Bob", {})])
    html = client.get("/collections/lists/1").text
    assert '<option value="7"' in html and "Only Bob" in html and "Only me" in html
    form = {"url": "https://mdblist.com/lists/u/top", "library_key": "1", "audience": "7", "name": "Top"}
    monkeypatch.setattr(plex, "cached_overview", lambda conn: ("S", "1", [plex.Library("1", "Movies", "movie", 6)]))
    client.post("/collections/lists/1", data=form)
    with connection(app.state.db_path) as conn:
        saved = get_list(conn, 1)
    assert (saved.audience, saved.audience_name) == ("7", "Bob")
    assert "Pick who sees" in client.post("/collections/lists/1", data={**form, "audience": "99"}).text


def test_form_offers_mdblist_lists_with_a_key(client, app, plex_server, monkeypatch):
    form = client.get("/collections/lists/new").text
    assert "1. Pick a list" in form and 'name="source" value="mdblist" checked' in form
    assert "/settings/mdblist" in form and 'hx-get="/collections/mdblist' not in form

    with connection(app.state.db_path) as conn:
        from app.settings_store import set_setting
        set_setting(conn, "mdblist.key", "k")
    monkeypatch.setattr(sources, "mdblist_lists", lambda client, key, which: [(f"{which}7", f"{which} list", 3)])
    assert 'hx-get="/collections/mdblist?selected="' in client.get("/collections/lists/new").text
    html = client.get("/collections/mdblist?selected=top7").text
    assert '<optgroup label="Your lists">' in html and '<optgroup label="Popular on MDBList">' in html
    assert 'value="top7" data-name="top list" selected' in html


def test_poster_sync_starts_after_the_writes_are_saved(client, app, plex_server, monkeypatch):
    """The poster sync writes from its own connection: the list sync must not hold the database."""
    import sqlite3

    from app.plex import sharing

    monkeypatch.setattr(sharing, "friends", lambda *a: [])
    starts = []

    class WritingPosters(FakePosters):
        def start(self, mode, only=None):
            other = sqlite3.connect(app.state.db_path, timeout=0.1)
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
            other.close()
            starts.append(mode)

    app.state.list_runner.posters = WritingPosters()
    saved = run(client, app, "live")
    with connection(app.state.db_path) as conn:
        set_scope_entry(conn, ScopeEntry("1", "Movies", saved.collection_key, "Top", None, True), True)
        conn.execute("UPDATE lists SET audience = 'owner'")  # the friends' step then saves a setting
    run(client, app, "live")
    assert starts == ["live"]
    assert not any("failed" in line.message for line in app.state.events.tail(20))

