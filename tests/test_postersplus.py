from app.posters.postersplus import adapt_for_plex, is_postersplus

CONFIGURATOR_URL = (
    "https://pp.example.com/poster?tmdb_id={tmdb_id?}&imdb_id={imdb_id?}&stremio_id={id}"
    "&type={type}&shape={shape}&pc=stremio_tv_nuvio&access_key=secret123&tg=medium&mw=lb:.5,pc:.1"
)


def test_detects_postersplus():
    assert is_postersplus(CONFIGURATOR_URL)
    assert not is_postersplus("https://btttr.cc/poster/imdb/poster-default/{imdb_id}.jpg?rs=LB")


def test_adapt_sets_plex_client_and_quality():
    adapted, changes = adapt_for_plex(CONFIGURATOR_URL)
    assert "pc=stremio_tv_nuvio" not in adapted
    assert adapted.endswith("&pc=plex&quality={quality}")
    # pc inside another value is not a client parameter
    assert "mw=lb:.5,pc:.1" in adapted
    assert len(changes) == 2


def test_adapt_replaces_literal_quality():
    adapted, _ = adapt_for_plex("https://pp.example.com/poster?tmdb_id={tmdb_id}&quality=4K&primary_client=nuvio")
    assert adapted == "https://pp.example.com/poster?tmdb_id={tmdb_id}&pc=plex&quality={quality}"


def test_adapt_is_idempotent():
    adapted, _ = adapt_for_plex(CONFIGURATOR_URL)
    again, changes = adapt_for_plex(adapted)
    assert again == adapted
    assert changes == []
