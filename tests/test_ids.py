from app.plex.ids import extract_ids
from tests.fakes import FakeItem, guid


def test_reads_guids():
    item = FakeItem(lite={"guids": [guid("imdb://tt0133093"), guid("tmdb://603"), guid("tvdb://169")]})
    assert extract_ids(item) == {"imdb": "tt0133093", "tmdb": "603", "tvdb": "169"}
    assert item.reloads == 0


def test_reloads_lite_object_without_guids():
    item = FakeItem(full={"guids": [guid("tmdb://603")]})
    assert extract_ids(item) == {"tmdb": "603"}
    assert item.reloads == 1


def test_ignores_other_schemes():
    item = FakeItem(lite={"guids": [guid("plex://movie/5d776"), guid("imdb://tt1")]})
    assert extract_ids(item) == {"imdb": "tt1"}
