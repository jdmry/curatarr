from app.db import connection, migrate
from app.lists.matching import match
from app.lists.sources import ListItem
from app.plex import guid_index
from app.plex.guid_index import CHECK_EVERY, FULL_EVERY, ensure_index, find
from tests.fakes import FakeSection, FakeServer, title


def setup(tmp_path, items):
    path = tmp_path / "t.db"
    migrate(path)
    section = FakeSection(1, "Movies", items=items)
    return path, section, FakeServer([section])


def test_full_then_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(guid_index, "PAGE", 2)
    a, b, c = title(1, "A", imdb="tt1", tmdb="11"), title(2, "B", tmdb="22"), title(3, "C", imdb="tt3")
    path, section, server = setup(tmp_path, [a, b, c])
    with connection(path) as conn:
        ensure_index(conn, server, section, now=1000)
        assert find(conn, "1", ["imdb://tt1", "tmdb://22", "imdb://tt9"]) == {"imdb://tt1": "1", "tmdb://22": "2"}
        assert len(server.queries) == 2  # pages of 2

        new = title(4, "D", imdb="tt4")
        new.addedAt = 1000 + CHECK_EVERY
        section.items.append(new)
        ensure_index(conn, server, section, now=1000 + 10)  # checked moments ago: nothing to do
        assert find(conn, "1", ["imdb://tt4"]) == {}
        ensure_index(conn, server, section, now=1000 + CHECK_EVERY + 1)
        assert "addedAt>>=" in server.queries[-1]
        assert find(conn, "1", ["imdb://tt4"]) == {"imdb://tt4": "4"}

        section.items.remove(a)
        ensure_index(conn, server, section, now=1000 + FULL_EVERY + 1)  # daily rebuild drops removed titles
        assert find(conn, "1", ["imdb://tt1"]) == {}


def test_match_keeps_order_kind_and_dedupes(tmp_path):
    path, section, server = setup(tmp_path, [title(1, "A", imdb="tt1", tmdb="11"), title(2, "B", tmdb="22")])
    items = [
        ListItem("movie", "B", tmdb_id="22"),
        ListItem("show", "Some show", tmdb_id="11"),
        ListItem("movie", "Missing", imdb_id="tt404"),
        ListItem("movie", "A", imdb_id="tt1"),
        ListItem("movie", "A again", tmdb_id="11"),
    ]
    with connection(path) as conn:
        ensure_index(conn, server, section)
        result = match(conn, "1", "movie", items)
    assert [(i.title, key) for i, key in result.owned] == [("B", "2"), ("A", "1")]
    assert [i.title for i in result.missing] == ["Missing"] and result.other_kind == 1


def test_background_build(tmp_path):
    import time

    path, section, server = setup(tmp_path, [title(1, "A", imdb="tt1")])
    with connection(path) as conn:
        assert ensure_index(conn, server, section, background=path) is False
        for _ in range(50):
            if not guid_index.building("1"):
                break
            time.sleep(0.05)
        assert ensure_index(conn, server, section, background=path) is True
        assert find(conn, "1", ["imdb://tt1"]) == {"imdb://tt1": "1"}
