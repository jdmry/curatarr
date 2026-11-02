"""External ids (IMDb, TMDB, TVDB) of a Plex item, read from its GUIDs."""

import logging

log = logging.getLogger(__name__)


def _parse_guids(guids) -> dict[str, str]:
    ids: dict[str, str] = {}
    for guid in guids or ():
        scheme, sep, value = (getattr(guid, "id", "") or "").partition("://")
        if sep and value and scheme in ("imdb", "tmdb", "tvdb"):
            ids.setdefault(scheme, value)
    return ids


def extract_ids(item) -> dict[str, str]:
    """Return {"imdb": "tt...", "tmdb": "...", "tvdb": "..."} (keys only when known).

    Items from library listings are partial objects whose guids may be
    missing: reload the item once in that case.
    """
    ids = _parse_guids(getattr(item, "guids", None))
    if not ids:
        try:
            item.reload()
        except Exception as exc:
            log.debug("Reload failed for %s: %s", getattr(item, "title", "?"), exc)
            return {}
        ids = _parse_guids(getattr(item, "guids", None))
    return ids
