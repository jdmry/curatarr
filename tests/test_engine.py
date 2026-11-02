from app.posters.sources import PosterSource
from app.scope import ScopeEntry
from app.sync.engine import collect_targets, evaluate, iter_section
from tests.fakes import FakeCollection, FakeSection, FakeServer, title

DEFAULT = PosterSource(1, "Default", "https://d.test/{imdb_id}.jpg?q={quality}", revision=3)
OTHER = PosterSource(2, "Other", "https://o.test/p?tmdb_id={tmdb_id}")


def test_iter_section_pages():
    section = FakeSection(1, "Movies", items=[title(i, f"M{i}") for i in range(450)])
    assert len(list(iter_section(section, page_size=200))) == 450
    assert section.pages == [0, 200, 400]


def test_collections_first_and_no_duplicates():
    a, b, c = title(1, "A"), title(2, "B"), title(3, "C")
    episode = title(4, "E", TYPE="episode")
    movies = FakeSection(1, "Movies", items=[a, b, c])
    marvel = FakeCollection(10, "Marvel", [b, episode])
    server = FakeServer([movies], [marvel])
    entries = [ScopeEntry("1", "Movies"), ScopeEntry("1", "Movies", "10", "Marvel", source_id=2)]
    warnings = []
    targets = list(collect_targets(server, entries, {1: DEFAULT, 2: OTHER}, DEFAULT, warnings.append))
    assert [(t.item.title, t.source.name, t.library) for t in targets] == [
        ("B", "Other", "Movies"), ("A", "Default", "Movies"), ("C", "Default", "Movies"),
    ]
    assert warnings == []


def test_missing_things_warn():
    server = FakeServer([FakeSection(1, "Movies", items=[title(1, "A")])])
    entries = [ScopeEntry("9", "Gone"), ScopeEntry("1", "Movies", "77", "Old collection"), ScopeEntry("1", "Movies")]
    warnings = []
    assert list(collect_targets(server, entries, {}, None, warnings.append)) == []
    assert len(warnings) == 3 and all("skipped" in w for w in warnings)


def test_evaluate_apply_unchanged_skipped():
    from app.sync.engine import Target

    item = title(1, "Dune", imdb="tt1", tmdb="5", resolution="4k", locked=True)
    outcome = evaluate(Target(item, "Movies", DEFAULT))
    assert outcome.action == "apply" and outcome.url == "https://d.test/tt1.jpg?q=4K"
    assert evaluate(Target(item, "Movies", DEFAULT), outcome.fingerprint).action == "unchanged"

    no_imdb = title(2, "X", tmdb="5")
    skipped = evaluate(Target(no_imdb, "Movies", DEFAULT))
    assert skipped.action == "skipped" and "imdb_id" in skipped.reason


def test_quality_not_read_when_disabled():
    from app.sync.engine import Target

    source = PosterSource(3, "PP", "https://p.test/p?imdb_id={imdb_id}&quality={quality}", no_quality="NONE",
                          read_quality=False)
    item = title(1, "Dune", imdb="tt1", resolution="4k")
    item.reload = lambda: (_ for _ in ()).throw(AssertionError("no reload expected"))
    assert evaluate(Target(item, "Movies", source)).url == "https://p.test/p?imdb_id=tt1&quality=NONE"


def test_unlocked_poster_is_sent_again():
    """Fix Match or a poster reset in Plex unlocks the field: same fingerprint, but the poster is gone."""
    from app.sync.engine import Target

    item = title(1, "Dune", imdb="tt1")
    first = evaluate(Target(item, "Movies", DEFAULT))
    again = evaluate(Target(item, "Movies", DEFAULT), first.fingerprint)
    assert again.action == "apply" and "replaced in Plex" in again.reason
