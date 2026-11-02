"""Fill a poster URL template with a title's values.

Templates use the placeholder syntax of AIOMetadata / Nuvio poster patterns:
`{name}` or `{name?}`. Rules:

* every value is URL-encoded;
* a placeholder with no value inside a query parameter drops that parameter;
* a placeholder with no value in the path skips the title for this source;
* `{quality}` with no detected quality takes the source's "no quality" value
  (PostersPlus needs a non-empty sentinel, see app.posters.postersplus).
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

from app.titles import TitleInfo

PLACEHOLDER = re.compile(r"\{([a-z_]+)\??\}")

VARIABLES = {
    "imdb_id": "IMDb id (tt...)",
    "tmdb_id": "TMDB id",
    "tvdb_id": "TVDB id",
    "id": "Stremio-style id: IMDb id, else tmdb:<id>",
    "type": "Title type (movie / series by default)",
    "shape": "Always 'poster' (portrait)",
    "quality": "Quality badges detected in the file, comma-separated",
    "title": "Title",
    "year": "Year",
}

# Characters left as-is: allowed by RFC 3986 in both path and query, and
# expected unencoded by services (tmdb:123, 4K,DV).
_SAFE = ":,"


@dataclass(frozen=True)
class TypeNames:
    movie: str = "movie"
    show: str = "series"


@dataclass(frozen=True)
class Rendered:
    url: str | None
    skipped: str | None = None  # reason when url is None


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER.findall(template)


def unknown_placeholders(template: str) -> list[str]:
    return [name for name in placeholders(template) if name not in VARIABLES]


def title_values(info: TitleInfo, types: TypeNames, no_quality: str) -> dict[str, str]:
    return {
        "imdb_id": info.imdb_id or "",
        "tmdb_id": info.tmdb_id or "",
        "tvdb_id": info.tvdb_id or "",
        "id": info.stremio_id or "",
        "type": types.movie if info.kind == "movie" else types.show,
        "shape": "poster",
        "quality": ",".join(info.quality) or no_quality,
        "title": info.title or "",
        "year": str(info.year) if info.year else "",
    }


def _fill(part: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Replace placeholders in part. Returns (result, names that were empty)."""
    missing: list[str] = []

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        value = values[name]
        if not value:
            missing.append(name)
        return quote(value, safe=_SAFE)

    return PLACEHOLDER.sub(repl, part), missing


def render(template: str, values: dict[str, str]) -> Rendered:
    template = template.strip()
    base, sep, query = template.partition("?")
    query, hash_sep, fragment = query.partition("#")
    if not sep:
        base, hash_sep, fragment = base.partition("#")

    url, missing = _fill(base, values)
    if missing:
        return Rendered(None, f"no {', '.join(dict.fromkeys(missing))} for this title")

    params = []
    for param in query.split("&") if query else []:
        filled, missing = _fill(param, values)
        if not missing:
            params.append(filled)
    if params:
        url += "?" + "&".join(params)
    if hash_sep:
        url += "#" + fragment
    return Rendered(url)
