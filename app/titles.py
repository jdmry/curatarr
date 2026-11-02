"""What we know about one Plex title, independent of Plex objects."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TitleInfo:
    kind: str  # "movie" or "show"
    title: str = ""
    year: int | None = None
    imdb_id: str | None = None
    tmdb_id: str | None = None
    tvdb_id: str | None = None
    quality: tuple[str, ...] = field(default_factory=tuple)

    @property
    def stremio_id(self) -> str | None:
        """Id in the form Stremio addons use: tt... first, else tmdb:..."""
        if self.imdb_id:
            return self.imdb_id
        if self.tmdb_id:
            return f"tmdb:{self.tmdb_id}"
        return None
