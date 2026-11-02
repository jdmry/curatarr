"""PostersPlus-specific handling of a pasted poster URL.

URLs copied from the PostersPlus configurator target Stremio clients. For
Plex we adjust two things:

* primary_client (short name `pc`) is set to `plex`: Stremio client profiles
  crop the poster edges, Plex shows posters uncropped;
* `quality` is set to the badges detected in the file. When it is missing or
  empty, PostersPlus looks up the quality available online and can show a
  4K REMUX badge on a 720p rip. So a title with no detected quality sends
  the sentinel NONE, which PostersPlus ignores as an unknown token.
"""

from urllib.parse import urlsplit

NO_QUALITY = "NONE"

_ID_PARAMS = {"tmdb_id", "imdb_id", "stremio_id"}
_CLIENT_PARAMS = {"primary_client", "pc"}


def _split(template: str) -> tuple[str, list[str]]:
    base, _, query = template.strip().partition("?")
    return base, [p for p in query.split("&") if p]


def _name(param: str) -> str:
    return param.partition("=")[0]


def is_postersplus(template: str) -> bool:
    base, params = _split(template)
    path = urlsplit(base).path.rstrip("/")
    return path.endswith("/poster") and any(_name(p) in _ID_PARAMS for p in params)


def adapt_for_plex(template: str) -> tuple[str, list[str]]:
    """Return (adjusted template, human-readable list of changes)."""
    base, params = _split(template)
    changes: list[str] = []

    clients = [p for p in params if _name(p) in _CLIENT_PARAMS]
    if clients != ["pc=plex"]:
        old = ", ".join(clients) or "none"
        changes.append(f"Client set to Plex (was: {old})")
    qualities = [p for p in params if _name(p) == "quality"]
    if qualities != ["quality={quality}"]:
        changes.append("Quality taken from the file (quality={quality})")

    params = [p for p in params if _name(p) not in _CLIENT_PARAMS | {"quality"}]
    params += ["pc=plex", "quality={quality}"]
    return f"{base}?{'&'.join(params)}", changes
