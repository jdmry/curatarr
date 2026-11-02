from app.posters.template import TypeNames, render, title_values, unknown_placeholders
from app.titles import TitleInfo

MOVIE = TitleInfo(kind="movie", title="Amélie & co", year=2001, imdb_id="tt0211915", tmdb_id="194",
                  quality=("1080P", "DV"))
SHOW_TMDB_ONLY = TitleInfo(kind="show", title="Show", tmdb_id="1399")


def values(info, no_quality=""):
    return title_values(info, TypeNames(), no_quality)


def test_fills_path_and_query():
    result = render("https://x.test/poster/imdb/poster-default/{imdb_id}.jpg?rs=LB", values(MOVIE))
    assert result.url == "https://x.test/poster/imdb/poster-default/tt0211915.jpg?rs=LB"


def test_empty_query_param_is_dropped():
    result = render("https://x.test/poster?tmdb_id={tmdb_id?}&imdb_id={imdb_id?}&type={type}",
                    values(SHOW_TMDB_ONLY))
    assert result.url == "https://x.test/poster?tmdb_id=1399&type=series"


def test_required_form_in_query_also_drops_param():
    result = render("https://x.test/p?imdb_id={imdb_id}&a=1", values(SHOW_TMDB_ONLY))
    assert result.url == "https://x.test/p?a=1"


def test_empty_path_placeholder_skips_title():
    result = render("https://x.test/poster/{imdb_id}.jpg", values(SHOW_TMDB_ONLY))
    assert result.url is None
    assert "imdb_id" in result.skipped


def test_stremio_id_falls_back_to_tmdb():
    assert render("https://x.test/p?stremio_id={id}", values(SHOW_TMDB_ONLY)).url == \
        "https://x.test/p?stremio_id=tmdb:1399"
    assert render("https://x.test/p?stremio_id={id}", values(MOVIE)).url == \
        "https://x.test/p?stremio_id=tt0211915"


def test_values_are_url_encoded():
    result = render("https://x.test/s?q={title}&y={year}", values(MOVIE))
    assert result.url == "https://x.test/s?q=Am%C3%A9lie%20%26%20co&y=2001"


def test_quality_joined_with_commas():
    assert render("https://x.test/p?quality={quality}", values(MOVIE)).url == "https://x.test/p?quality=1080P,DV"


def test_no_quality_uses_source_value():
    assert render("https://x.test/p?quality={quality}", values(SHOW_TMDB_ONLY, "NONE")).url == \
        "https://x.test/p?quality=NONE"
    assert render("https://x.test/p?quality={quality}&a=1", values(SHOW_TMDB_ONLY)).url == "https://x.test/p?a=1"


def test_literal_params_are_left_untouched():
    template = "https://x.test/poster?sp=default2,wins%400&mw=lb:.5,rt:.15&bg1=&tmdb_id={tmdb_id}"
    assert render(template, values(MOVIE)).url == \
        "https://x.test/poster?sp=default2,wins%400&mw=lb:.5,rt:.15&bg1=&tmdb_id=194"


def test_shape_and_type_mapping():
    result = render("https://x.test/{type}/{tmdb_id}?shape={shape}", title_values(SHOW_TMDB_ONLY, TypeNames(show="tv"), ""))
    assert result.url == "https://x.test/tv/1399?shape=poster"


def test_unknown_placeholders():
    assert unknown_placeholders("https://x.test/{imdb_id}?a={foo}&b={bar?}") == ["foo", "bar"]
