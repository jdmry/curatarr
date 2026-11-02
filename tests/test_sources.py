import httpx

from app.db import connection, migrate
from app.posters.fetch import fetch_poster
from app.posters.sources import (
    PosterSource,
    analyze,
    delete_source,
    get_default_source,
    get_source,
    list_sources,
    parse_headers,
    restore_headers,
    restore_secrets,
    save_source,
    set_default_source,
)
from app.titles import TitleInfo

PP_URL = "https://pp.example.com/poster?tmdb_id={tmdb_id?}&imdb_id={imdb_id?}&type={type}&pc=stremio_tv_nuvio&access_key=k3y"


def test_analyze_postersplus():
    analysis = analyze(PP_URL)
    assert analysis.kind == "postersplus"
    assert analysis.default_name == "PostersPlus"
    assert analysis.template.endswith("&pc=plex&quality={quality}")
    assert analysis.secret_params == ["access_key"]
    assert analysis.variables == ["tmdb_id", "imdb_id", "type", "quality"]
    assert not analysis.warnings


def test_analyze_generic_and_errors():
    analysis = analyze("https://btttr.cc/poster/imdb/poster-default/{imdb_id}.jpg?rs=LB")
    assert analysis.kind == "generic" and analysis.default_name == "btttr.cc" and not analysis.changes
    assert analyze("").error
    assert analyze("ftp://x/{imdb_id}").error
    warnings = analyze("https://x.test/static.jpg?a={nope}").warnings
    assert any("{nope}" in w for w in warnings) and any("same image" in w for w in warnings)


def test_restore_secrets():
    old = "https://x.test/p?access_key=real&a=1"
    assert restore_secrets("https://x.test/p?access_key=***&a=2", old) == "https://x.test/p?access_key=real&a=2"
    assert restore_secrets("https://x.test/p?access_key=new", old) == "https://x.test/p?access_key=new"


def test_headers():
    assert parse_headers("X-Api-Key: abc\n\nbad line\nAccept: image/*") == {"X-Api-Key": "abc", "Accept": "image/*"}
    assert restore_headers({"X-Api-Key": "***", "B": "2"}, {"X-Api-Key": "abc"}) == {"X-Api-Key": "abc", "B": "2"}


def test_source_render_and_mask():
    source = PosterSource(None, "PP", analyze(PP_URL).template, kind="postersplus", no_quality="NONE")
    assert source.masked_template.count("***") == 1 and "k3y" not in source.masked_template
    url = source.render(TitleInfo("show", tmdb_id="1399")).url
    assert url == "https://pp.example.com/poster?tmdb_id=1399&type=series&access_key=k3y&pc=plex&quality=NONE"


def test_storage_default_and_revision(tmp_path):
    path = tmp_path / "t.db"
    migrate(path)
    with connection(path) as conn:
        first = save_source(conn, PosterSource(None, "A", "https://a.test/{imdb_id}.jpg"))
        second = save_source(conn, PosterSource(None, "B", "https://b.test/{imdb_id}.jpg"))
        assert get_default_source(conn).id == first

        source = get_source(conn, second)
        source.name = "B2"
        save_source(conn, source)
        assert get_source(conn, second).revision == 1  # name only

        source.url_template = "https://b.test/{tmdb_id}.jpg"
        save_source(conn, source)
        assert get_source(conn, second).revision == 2

        set_default_source(conn, second)
        assert [s.is_default for s in list_sources(conn)] == [True, False]
        delete_source(conn, second)
        assert get_default_source(conn).id == first


def test_fetch_poster_ok_and_errors():
    def handler(request):
        if request.url.path == "/ok.jpg":
            assert request.headers["X-Api-Key"] == "abc"
            return httpx.Response(200, content=b"img", headers={"content-type": "image/jpeg"})
        if request.url.path == "/html":
            return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        return httpx.Response(403, text="bad key sekret", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(handler)
    ok = fetch_poster("https://s.test/ok.jpg", {"X-Api-Key": "abc"}, 10, ["abc"], transport)
    assert ok.ok and ok.content == b"img" and ok.content_type == "image/jpeg"

    not_image = fetch_poster("https://s.test/html", {}, 10, [], transport)
    assert not not_image.ok and "text/html" in not_image.error

    denied = fetch_poster("https://s.test/denied", {}, 10, ["sekret"], transport)
    assert denied.status == 403 and "sekret" not in denied.error and "403" in denied.error


def test_fetch_poster_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = fetch_poster("https://s.test/x.jpg", {}, 3, [], httpx.MockTransport(handler))
    assert not result.ok and "3 s" in result.error
