"""Plex items as TitleInfo, and title search across libraries."""

from dataclasses import dataclass

from app.plex.ids import extract_ids
from app.plex.quality import title_quality
from app.titles import TitleInfo


@dataclass
class SearchResult:
    rating_key: str
    title: str
    year: int | None
    type: str
    library: str
    thumb: str | None


def search_titles(server, query: str, per_library: int = 8) -> list[SearchResult]:
    results = []
    for section in server.library.sections():
        if section.type not in ("movie", "show"):
            continue
        for item in section.search(title=query, maxresults=per_library):
            results.append(SearchResult(
                str(item.ratingKey), item.title, getattr(item, "year", None), item.TYPE, section.title,
                getattr(item, "thumb", None),
            ))
    return results


def title_info(item, with_quality: bool = True) -> TitleInfo:
    ids = extract_ids(item)
    return TitleInfo(
        kind="movie" if item.TYPE == "movie" else "show",
        title=item.title or "",
        year=getattr(item, "year", None),
        imdb_id=ids.get("imdb"),
        tmdb_id=ids.get("tmdb"),
        tvdb_id=ids.get("tvdb"),
        quality=tuple(title_quality(item)) if with_quality else (),
    )
