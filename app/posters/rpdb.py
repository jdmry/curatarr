"""RPDB (ratingposterdb.com): posters with ratings, from an API key and a few choices.

The poster URL is built here, so nobody has to write it by hand:
https://api.ratingposterdb.com/{key}/imdb/{style}/{imdb_id}.jpg?fallback=true
The key sits in the path, where URL secret detection can't see it.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

HOST = "api.ratingposterdb.com"
STYLES = {
    "poster-default": "Default",
    "poster-certs": "Certifications",
    "poster-mc": "Metacritic",
    "poster-rt": "Rotten Tomatoes",
    "textless-default": "Textless, default",
    "textless-certs": "Textless, certifications",
    "textless-mc": "Textless, Metacritic",
    "textless-rt": "Textless, Rotten Tomatoes",
}
SIZES = {"medium": "Medium, 580×859", "large": "Large, 1280×1896 (tier 2+)", "verylarge": "Very large, 2000×2962 (tier 3+)"}


@dataclass
class RpdbOptions:
    key: str = ""
    style: str = "poster-default"
    lang: str = ""
    size: str = "medium"
    fallback: bool = True


def is_rpdb(template: str) -> bool:
    return urlsplit(template.strip()).hostname == HOST


def build(options: RpdbOptions) -> str:
    style = options.style if options.style in STYLES else "poster-default"
    params = {}
    if options.fallback:
        params["fallback"] = "true"
    if options.lang.strip():
        params["lang"] = options.lang.strip()
    if options.size in SIZES and options.size != "medium":
        params["imageSize"] = options.size
    query = f"?{urlencode(params)}" if params else ""
    return f"https://{HOST}/{options.key.strip()}/imdb/{style}/{{imdb_id}}.jpg{query}"


def parse(template: str) -> RpdbOptions:
    parts = urlsplit(template.strip())
    path = parts.path.strip("/").split("/")
    params = dict(parse_qsl(parts.query))
    return RpdbOptions(
        key=path[0] if path else "",
        style=path[2] if len(path) > 2 else "poster-default",
        lang=params.get("lang", ""),
        size=params.get("imageSize", "medium"),
        fallback=params.get("fallback") == "true",
    )


def key_of(template: str) -> str:
    return parse(template).key if is_rpdb(template) else ""
