"""What to do with each title: walk the scope, render the URL, decide."""

import hashlib
import io
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app.plex.titles import title_info
from app.posters.sources import PosterSource
from app.scope import ScopeEntry
from app.secrets import mask
from app.titles import TitleInfo

PAGE_SIZE = 200


@dataclass
class Target:
    item: Any
    library: str
    source: PosterSource


@dataclass
class Outcome:
    action: str  # apply, unchanged, skipped, error
    info: TitleInfo | None = None
    url: str | None = None
    masked_url: str | None = None
    fingerprint: str | None = None
    reason: str | None = None


def iter_section(section, page_size: int = PAGE_SIZE) -> Iterator[Any]:
    """All movies or shows of a library, fetched page by page."""
    start = 0
    while True:
        page = section.search(container_start=start, container_size=page_size, maxresults=page_size)
        yield from page
        if len(page) < page_size:
            return
        start += page_size


def collect_targets(
    server,
    entries: list[ScopeEntry],
    sources: dict[int, PosterSource],
    default: PosterSource | None,
    warn: Callable[[str], None],
) -> Iterator[Target]:
    """Titles to process, each once. Collections come first so their own source wins."""
    sections = {str(s.key): s for s in server.library.sections()}
    seen: set[str] = set()
    for entry in sorted(entries, key=lambda e: e.is_library):
        name = entry.collection_title or entry.library_title
        source = sources.get(entry.source_id) if entry.source_id else default
        if source is None:
            warn(f"{name}: no poster source (add one or pick a default), skipped")
            continue
        section = sections.get(entry.library_key)
        if section is None:
            warn(f"Library {entry.library_title} no longer exists on the server, skipped")
            continue
        if entry.is_library:
            items = iter_section(section)
        else:
            try:
                items = server.fetchItem(int(entry.collection_key)).items()
            except Exception:
                warn(f"Collection {entry.collection_title} no longer exists on the server, skipped")
                continue
        for item in items:
            key = str(item.ratingKey)
            if item.TYPE not in ("movie", "show") or key in seen:
                continue
            seen.add(key)
            yield Target(item, section.title, source)


def fingerprint(source: PosterSource, masked_url: str) -> str:
    return hashlib.sha256(f"{source.id}:{source.revision}:{masked_url}".encode()).hexdigest()[:32]


def poster_locked(item) -> bool:
    """Plex locks the poster on upload. Fix Match or a reset unlocks it, so it must be sent again."""
    return any(field.name == "thumb" and field.locked for field in getattr(item, "fields", None) or [])


def evaluate(target: Target, previous_fingerprint: str | None = None) -> Outcome:
    source = target.source
    info = title_info(target.item, with_quality=source.uses_quality)
    rendered = source.render(info)
    if rendered.url is None:
        return Outcome("skipped", info, reason=rendered.skipped)
    masked = mask(rendered.url, source.secrets)
    digest = fingerprint(source, masked)
    if digest != previous_fingerprint:
        return Outcome("apply", info, rendered.url, masked, digest)
    if not poster_locked(target.item):
        return Outcome("apply", info, rendered.url, masked, digest, reason="poster was replaced in Plex")
    return Outcome("unchanged", info, rendered.url, masked, digest)


def upload(item, content: bytes) -> None:
    """Send the image as is: Plex takes WebP as well as JPEG and PNG."""
    item.uploadPoster(filepath=io.BytesIO(content))


def remember(conn: sqlite3.Connection, rating_key: str, digest: str) -> None:
    """What was sent last, so a sync doesn't send the same poster again."""
    conn.execute(
        "INSERT INTO poster_state (rating_key, fingerprint) VALUES (?, ?) ON CONFLICT (rating_key)"
        " DO UPDATE SET fingerprint = excluded.fingerprint, applied_at = CURRENT_TIMESTAMP",
        (rating_key, digest),
    )


def source_for(item, entries: list[ScopeEntry], sources: dict[int, PosterSource], default: PosterSource | None):
    """The service a sync would use for this title: its collection's, its library's, else the default."""
    library = str(getattr(item, "librarySectionID", ""))
    collections = {c.tag for c in getattr(item, "collections", None) or []}
    for entry in sorted(entries, key=lambda e: e.is_library):
        if entry.library_key != library or not (entry.is_library or entry.collection_title in collections):
            continue
        if entry.source_id in sources:
            return sources[entry.source_id]
        return default
    return default
