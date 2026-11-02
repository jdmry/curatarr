import httpx
import pytest

from app.lists import sources
from app.lists.sources import ListError, ListItem, check_tmdb_key, fetch, parse


def test_parse():
    ref = parse("https://mdblist.com/lists/garycrawfordgc/latest-tv-shows")
    assert (ref.kind, ref.path, ref.name) == ("mdblist", "garycrawfordgc/latest-tv-shows", "Latest Tv Shows")
    assert parse("mdblist.com/lists/u/top-movies/json/").path == "u/top-movies"
    assert parse("https://www.themoviedb.org/list/8512345-best-of").path == "list/8512345"
    assert parse("https://www.themoviedb.org/collection/10-star-wars-collection").path == "collection/10"
    assert parse("tmdb:trending/movie/week").name == "Trending movies this week"
    for bad in ("https://letterboxd.com/u/list/x/", "tmdb:nope", "https://mdblist.com/"):
        with pytest.raises(ListError):
            parse(bad)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_mdblist():
    def handler(request):
        assert request.url.path == "/lists/u/top/json"
        return httpx.Response(200, json=[
            {"id": 917496, "title": "Beetlejuice Beetlejuice", "imdb_id": "tt2049403", "tvdbid": 65987,
             "mediatype": "movie", "release_year": 2024},
            {"id": 1399, "title": "Game of Thrones", "imdb_id": "tt0944947", "tvdbid": 121361, "mediatype": "show"},
        ])

    result = fetch(parse("https://mdblist.com/lists/u/top"), client(handler))
    assert result.items == [
        ListItem("movie", "Beetlejuice Beetlejuice", 2024, "917496", "tt2049403", "65987"),
        ListItem("show", "Game of Thrones", None, "1399", "tt0944947", "121361"),
    ]
    assert result.items[0].guids == ["imdb://tt2049403", "tmdb://917496", "tvdb://65987"]


def test_mdblist_private_list():
    result = client(lambda r: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ListError, match="public"):
        fetch(parse("https://mdblist.com/lists/u/private"), result)


def test_tmdb_needs_key():
    with pytest.raises(ListError, match="TMDB key|TMDB API key"):
        fetch(parse("tmdb:movie/popular"), client(lambda r: httpx.Response(200)))


def test_tmdb_pages_and_kinds():
    seen = []

    def handler(request):
        seen.append(request)
        page = int(request.url.params["page"])
        results = [{"id": page * 10 + i, "name": f"Show {page}.{i}", "first_air_date": "2024-05-01"} for i in range(2)]
        return httpx.Response(200, json={"page": page, "total_pages": 3, "results": results})

    result = fetch(parse("tmdb:tv/popular"), client(handler), "abc123")
    assert len(result.items) == 6 and result.items[0] == ListItem("show", "Show 1.0", 2024, "10")
    assert seen[0].url.params["api_key"] == "abc123" and "authorization" not in seen[0].headers


def test_tmdb_list_and_bearer_token():
    def handler(request):
        assert request.headers["authorization"] == "Bearer eyJtoken" and "api_key" not in request.url.params
        return httpx.Response(200, json={"name": "Best of", "total_pages": 1, "items": [
            {"id": 1, "media_type": "movie", "title": "A", "release_date": "1999-01-01"},
            {"id": 2, "media_type": "tv", "name": "B"},
        ]})

    result = fetch(parse("https://www.themoviedb.org/list/77"), client(handler), "eyJtoken")
    assert result.name == "Best of" and [i.kind for i in result.items] == ["movie", "show"]


def test_tmdb_collection_in_release_order():
    parts = [{"id": 2, "title": "Two", "release_date": "1980-05-21"}, {"id": 1, "title": "One", "release_date": "1977-05-25"}]
    handler = lambda r: httpx.Response(200, json={"name": "Star Wars Collection", "parts": parts})  # noqa: E731
    result = fetch(parse("https://www.themoviedb.org/collection/10"), client(handler), "k")
    assert result.name == "Star Wars Collection" and [i.title for i in result.items] == ["One", "Two"]


def test_tmdb_key_check_hides_key():
    assert check_tmdb_key(client(lambda r: httpx.Response(200, json={})), "good") is None
    assert "refused" in check_tmdb_key(client(lambda r: httpx.Response(401)), "bad")

    def boom(request):
        raise httpx.ConnectError(f"failed for {request.url}")

    error = check_tmdb_key(client(boom), "s3cretkey")
    assert "s3cretkey" not in error and sources.TMDB_API not in error


def test_mdblist_with_api_key_in_list_order_and_private():
    seen = []

    def handler(request):
        seen.append(request.url)
        assert request.url.params["apikey"] == "mdbkey"
        return httpx.Response(200, json={
            "movies": [{"id": 1, "rank": 2, "title": "B", "imdb_id": "tt2", "mediatype": "movie", "release_year": 2020}],
            "shows": [{"id": 9, "rank": 1, "title": "A", "imdb_id": "tt9", "tvdb_id": 99, "mediatype": "show"}],
        })

    result = fetch(parse("mdblist:4242"), client(handler), mdblist_key="mdbkey")
    assert [i.title for i in result.items] == ["A", "B"] and result.items[0].tvdb_id == "99"
    assert seen[0].path == "/lists/4242/items"
    fetch(parse("https://mdblist.com/lists/u/top"), client(handler), mdblist_key="mdbkey")
    assert seen[1].path == "/lists/u/top/items"  # pasted URLs go through the API too: private lists work

    with pytest.raises(ListError, match="needs the MDBList API key"):
        fetch(parse("mdblist:4242"), client(handler))


def test_mdblist_lists_and_key_check():
    def handler(request):
        if request.url.params["apikey"] != "good":
            return httpx.Response(403, text="bad key good")
        if request.url.path == "/user":
            return httpx.Response(200, json={"username": "jd"})
        assert request.url.path in ("/lists/user", "/lists/top")
        return httpx.Response(200, json=[{"id": 5, "name": "Mine", "items": 12}, {"name": "no id"}])

    assert sources.mdblist_lists(client(handler), "good", "user") == [("5", "Mine", 12)]
    assert sources.check_mdblist_key(client(handler), "good") == ("jd", None)
    username, error = sources.check_mdblist_key(client(handler), "nope")
    assert username is None and "MDBList refused the API key" in error and "nope" not in error


MANIFEST = "https://addon.test/c0nf1g/manifest.json"


def stremio_handler(pages):
    def handler(request):
        path = request.url.path
        if path.endswith("/manifest.json"):
            return httpx.Response(200, json={"catalogs": [
                {"type": "movie", "id": "nfx", "name": "Netflix"},
                {"type": "series", "id": "nfx", "name": "Netflix"},
                {"type": "series", "id": "search", "name": "Search", "extra": [{"name": "search", "isRequired": True}]},
                {"type": "channel", "id": "tv", "name": "TV"},
            ]})
        skip = int(path.rsplit("skip=", 1)[1].removesuffix(".json")) if "skip=" in path else 0
        return httpx.Response(200, json={"metas": pages.get(skip, [])})
    return handler


def test_stremio_catalogs_and_items():
    page = [{"id": "tt1", "type": "series", "name": "Lupin", "releaseInfo": "2021–", "moviedb_id": 96677},
            {"id": "fs:9", "type": "series", "name": "No ids"}]
    http = client(stremio_handler({0: page, 2: [{"id": "tt2", "name": "Two", "imdb_id": "tt2"}]}))
    assert sources.stremio_catalogs(http, MANIFEST) == [("movie/nfx", "Netflix (movies)"), ("series/nfx", "Netflix (shows)")]

    ref = parse(f"{MANIFEST}#series/nfx")
    assert ref.kind == "stremio"
    result = fetch(ref, http)
    assert result.name == "Netflix (shows)"
    assert result.items[0] == ListItem("show", "Lupin", 2021, "96677", "tt1", None)
    assert [i.imdb_id for i in result.items] == ["tt1", None, "tt2"]

    # An addon that ignores skip sends its first page again: stop there.
    result = fetch(ref, client(stremio_handler({0: page, 2: page})))
    assert len(result.items) == 2


def test_stremio_hides_its_configuration():
    assert sources.mask_stremio(f"{MANIFEST}#movie/nfx") == "https://addon.test/***/manifest.json#movie/nfx"
    with pytest.raises(ListError, match="Load the addon's catalogs"):
        parse(MANIFEST)

    def down(request):
        raise httpx.ConnectError("boom c0nf1g")

    with pytest.raises(ListError) as error:
        fetch(parse(f"{MANIFEST}#movie/nfx"), client(down))
    assert "c0nf1g" not in str(error.value)
