"""Quality badges detected from a title's actual file.

Vocabulary (the value of the {quality} placeholder, in this order):
4K, 1080P, REMUX, WEBDL, DV, HDR10, ATMOS, DTSX.
"""

import logging
import re

log = logging.getLogger(__name__)

ORDER = ("4K", "1080P", "REMUX", "WEBDL", "DV", "HDR10", "ATMOS", "DTSX")

_RESOLUTION_RANK = {"4k": 4, "2160": 4, "1080": 3, "720": 2, "576": 1, "480": 1, "sd": 0}

# No word boundary: often glued to other words (BDRemux, BluRay.REMUX).
_REMUX = re.compile(r"remux", re.IGNORECASE)
# Not preceded/followed by a letter or digit (underscores count as separators).
_WEBDL = re.compile(r"(?<![a-z0-9])web[-_. ]?dl(?![a-z0-9])", re.IGNORECASE)
_ATMOS = re.compile(r"atmos", re.IGNORECASE)
_DTSX = re.compile(r"dts[-: ]?x(?![a-z0-9])", re.IGNORECASE)

VIDEO, AUDIO = 1, 2


def _rank(media) -> int:
    resolution = str(getattr(media, "videoResolution", "") or "").lower().removesuffix("p")
    return _RESOLUTION_RANK.get(resolution, -1)


def _resolution_badge(media) -> str | None:
    rank = _rank(media)
    if rank == 4:
        return "4K"
    if rank == 3:
        return "1080P"
    return None


def _streams(media) -> list:
    return [stream for part in getattr(media, "parts", None) or () for stream in part.streams or ()]


def _best_media(item):
    medias = list(getattr(item, "media", None) or ())
    return max(medias, key=_rank) if medias else None


def _stream_text(stream) -> str:
    return f"{getattr(stream, 'displayTitle', '') or ''} {getattr(stream, 'extendedDisplayTitle', '') or ''}"


def extract_quality(item) -> list[str]:
    """Badges for a movie or an episode (anything with .media).

    Streams are only loaded on a full object, so the item is reloaded once
    when its best media has none.
    """
    media = _best_media(item)
    if media is None:
        return []
    if not _streams(media):
        try:
            item.reload()
        except Exception as exc:
            log.debug("Reload failed for %s: %s", getattr(item, "title", "?"), exc)
        media = _best_media(item) or media

    badges: set[str] = set()
    resolution = _resolution_badge(media)
    if resolution:
        badges.add(resolution)

    streams = _streams(media)
    video = [s for s in streams if getattr(s, "streamType", None) == VIDEO]
    audio = [s for s in streams if getattr(s, "streamType", None) == AUDIO]

    # Sonarr/Radarr often rename files, but Plex keeps the original release
    # name in the video stream's titles: look in both.
    source_text = " ".join(
        [*(getattr(part, "file", "") or "" for part in media.parts or ()), *(_stream_text(s) for s in video)]
    )
    if _REMUX.search(source_text):
        badges.add("REMUX")
    if _WEBDL.search(source_text):
        badges.add("WEBDL")

    if any(getattr(s, "DOVIPresent", False) for s in video):
        badges.add("DV")
    elif any(getattr(s, "colorTrc", None) == "smpte2084" for s in video):
        badges.add("HDR10")

    audio_text = " ".join(_stream_text(s) for s in audio)
    if _ATMOS.search(audio_text):
        badges.add("ATMOS")
    if _DTSX.search(audio_text):
        badges.add("DTSX")

    return [badge for badge in ORDER if badge in badges]


def _first_regular(items, number):
    """The item numbered 1, else the lowest-numbered one, ignoring 0 (specials)."""
    regular = [i for i in items if (number(i) or 0) > 0]
    if not regular:
        return None
    return next((i for i in regular if number(i) == 1), None) or min(regular, key=number)


def representative_episode(show):
    """S01E01, else the first episode outside season 0 (specials).

    Goes through the season list, then that season's episodes: loading every
    episode of a long show is much slower.
    """
    try:
        season = _first_regular(show.seasons(), lambda s: getattr(s, "index", None))
        if season is None:
            return None
        return _first_regular(season.episodes(), lambda e: getattr(e, "index", None))
    except Exception as exc:
        log.debug("Could not load episodes for %s: %s", getattr(show, "title", "?"), exc)
        return None


def title_quality(item) -> list[str]:
    """Badges for a movie, or for a show via its representative episode."""
    if getattr(item, "TYPE", None) == "show":
        episode = representative_episode(item)
        return extract_quality(episode) if episode is not None else []
    return extract_quality(item)
