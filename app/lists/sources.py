"""Where lists come from: paste a MDBList or TMDB URL, get the titles in order."""

import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import httpx

from app.secrets import MASK, mask

TMDB_API = "https://api.themoviedb.org/3"
MDBLIST_API = "https://api.mdblist.com"
# A collection holds at most 500 titles: one page of list items is enough.
MDBLIST_ITEMS = 1000
STREMIO_TYPES = {"movie": "movie", "series": "show"}
STREMIO_MAX_PAGES = 5
MAX_TITLES = 500  # the most a collection holds
TIMEOUT = 30
# TMDB pages hold 20 titles; a list only needs enough of them to fill its collection.
TMDB_MAX_PAGES = 10

PRESETS = {
    "trending/movie/week": "Trending movies this week",
    "trending/movie/day": "Trending movies today",
    "trending/tv/week": "Trending shows this week",
    "trending/tv/day": "Trending shows today",
    "movie/popular": "Popular movies",
    "movie/top_rated": "Top rated movies",
    "movie/now_playing": "Movies in theaters",
    "movie/upcoming": "Upcoming movies",
    "tv/popular": "Popular shows",
    "tv/top_rated": "Top rated shows",
    "tv/on_the_air": "Shows on the air",
    "tv/airing_today": "Shows airing today",
}

_MDBLIST_PATH = re.compile(r"^/lists/([^/]+)/([^/]+?)(?:/json)?/?$")
_TMDB_PATH = re.compile(r"^/(list|collection)/(\d+)")


class ListError(Exception):
    pass


@dataclass(frozen=True)
class ListRef:
    kind: str  # mdblist, tmdb, stremio
    # mdblist: user/slug, or the list id (picked with an API key); tmdb: API path such as list/123;
    # stremio: manifest URL#type/catalog id
    path: str
    name: str

    @property
    def label(self) -> str:
        return {"mdblist": "MDBList", "tmdb": "TMDB", "stremio": "Stremio addon"}[self.kind]

    @property
    def needs_tmdb_key(self) -> bool:
        return self.kind == "tmdb"


@dataclass(frozen=True)
class ListItem:
    kind: str  # movie, show
    title: str
    year: int | None = None
    tmdb_id: str | None = None
    imdb_id: str | None = None
    tvdb_id: str | None = None

    @property
    def guids(self) -> list[str]:
        """Plex guids to look for, most reliable first."""
        ids = (("imdb", self.imdb_id), ("tmdb", self.tmdb_id), ("tvdb", self.tvdb_id))
        return [f"{name}://{value}" for name, value in ids if value]


@dataclass
class FetchedList:
    name: str
    items: list[ListItem] = field(default_factory=list)


def parse(raw: str) -> ListRef:
    value = raw.strip()
    if value.startswith("mdblist:"):
        number = value.removeprefix("mdblist:").strip()
        if not number.isdigit():
            raise ListError("Unknown MDBList list.")
        return ListRef("mdblist", number, f"MDBList list {number}")
    if value.startswith("tmdb:"):
        path = value.removeprefix("tmdb:").strip("/")
        if path not in PRESETS:
            raise ListError("Unknown TMDB list.")
        return ListRef("tmdb", path, PRESETS[path])

    url = urlparse(value if "://" in value else f"https://{value}")
    host = (url.hostname or "").removeprefix("www.")
    if url.path.endswith("/manifest.json"):
        kind, _, catalog = url.fragment.partition("/")
        if kind not in STREMIO_TYPES or not catalog:
            raise ListError("Load the addon's catalogs and pick one.")
        return ListRef("stremio", value, catalog)
    if host == "mdblist.com" and (match := _MDBLIST_PATH.match(url.path)):
        user, slug = match.groups()
        return ListRef("mdblist", f"{user}/{slug}", slug.replace("-", " ").replace("_", " ").title())
    if host == "themoviedb.org" and (match := _TMDB_PATH.match(url.path)):
        kind, number = match.groups()
        return ListRef("tmdb", f"{kind}/{number}", f"TMDB {kind} {number}")
    raise ListError("Pick a list, or paste a MDBList or TMDB list URL or a Stremio addon manifest URL.")


def _year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def _str(value) -> str | None:
    return str(value) if value not in (None, "", 0) else None


def fetch(ref: ListRef, client: httpx.Client, tmdb_key: str | None = None, mdblist_key: str | None = None) -> FetchedList:
    if ref.kind == "mdblist":
        if mdblist_key:
            return _fetch_mdblist_api(ref, client, mdblist_key)
        if ref.path.isdigit():
            raise ListError("This MDBList list needs the MDBList API key: add it in Settings → MDBList.")
        return _fetch_mdblist(ref, client)
    if ref.kind == "stremio":
        return _fetch_stremio(ref, client)
    if not tmdb_key:
        raise ListError("TMDB lists need a TMDB API key: add it in Settings → TMDB.")
    return _fetch_tmdb(ref, client, tmdb_key)


def _get(client: httpx.Client, url: str, secrets: list[str], service: str = "TMDB", **kwargs) -> dict | list:
    try:
        response = client.get(url, timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        raise ListError(mask(f"Could not reach {urlparse(url).hostname}: {type(exc).__name__}", secrets)) from None
    if response.status_code in (401, 403) and service in ("TMDB", "MDBList"):
        raise ListError(f"{service} refused the API key. Check it in Settings → {service}.")
    if response.status_code == 404:
        raise ListError("List not found. Is it public?")
    if response.status_code != 200:
        raise ListError(f"{urlparse(url).hostname} answered HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise ListError(f"{urlparse(url).hostname} did not send a list. Is it public?") from None


def _fetch_mdblist(ref: ListRef, client: httpx.Client) -> FetchedList:
    data = _get(client, f"https://mdblist.com/lists/{ref.path}/json", [])
    if not isinstance(data, list):
        raise ListError("MDBList did not send a list. Is it public?")
    return FetchedList(ref.name, [_mdblist_item(row) for row in data])


def _mdblist_item(row: dict) -> ListItem:
    ids = row.get("ids") or {}
    return ListItem(
        kind="show" if row.get("mediatype") == "show" else "movie",
        title=row.get("title") or "",
        year=_year(row.get("release_year")),
        tmdb_id=_str(ids.get("tmdb") or row.get("id")),
        imdb_id=_str(ids.get("imdb") or row.get("imdb_id")),
        tvdb_id=_str(ids.get("tvdb") or row.get("tvdb_id") or row.get("tvdbid")),
    )


def _fetch_mdblist_api(ref: ListRef, client: httpx.Client, key: str) -> FetchedList:
    """Private lists too. Movies and shows come apart: put them back in the list's order."""
    data = _get(client, f"{MDBLIST_API}/lists/{ref.path}/items", [key], "MDBList",
                params={"apikey": key, "limit": MDBLIST_ITEMS})
    if not isinstance(data, dict):
        raise ListError("MDBList did not send a list.")
    rows = [*(data.get("movies") or []), *(data.get("shows") or [])]
    rows.sort(key=lambda row: row.get("rank") or 0)
    return FetchedList(ref.name, [_mdblist_item(row) for row in rows])


def mdblist_lists(client: httpx.Client, key: str, which: str) -> list[tuple[str, str, int | None]]:
    """(id, name, item count) of the user's own lists ("user") or of the most popular ones ("top")."""
    params = {"apikey": key} if which == "user" else {"apikey": key, "limit": 50}
    data = _get(client, f"{MDBLIST_API}/lists/{which}", [key], "MDBList", params=params)
    if not isinstance(data, list):
        raise ListError("MDBList did not send lists.")
    return [(str(row["id"]), row.get("name") or str(row["id"]), row.get("items")) for row in data if row.get("id")]


def check_mdblist_key(client: httpx.Client, key: str) -> tuple[str | None, str | None]:
    """(username, None) when MDBList accepts the key, else (None, the error)."""
    try:
        data = _get(client, f"{MDBLIST_API}/user", [key], "MDBList", params={"apikey": key})
    except ListError as exc:
        return None, str(exc)
    return (data.get("username") if isinstance(data, dict) else None) or "your account", None


def stremio_secrets(manifest_url: str) -> list[str]:
    """Addons keep their configuration, tokens included, in the path before manifest.json."""
    path = urlparse(manifest_url.partition("#")[0]).path
    return [part for part in path.split("/")[:-1] if part]


def mask_stremio(url: str) -> str:
    return mask(url, stremio_secrets(url))


def stremio_catalogs(client: httpx.Client, manifest_url: str) -> list[tuple[str, str]]:
    """("type/catalog id", name) of the addon's movie and show catalogs that need no search or genre."""
    manifest = manifest_url.partition("#")[0]
    data = _get(client, manifest, stremio_secrets(manifest), "Stremio addon")
    if not isinstance(data, dict) or not isinstance(data.get("catalogs"), list):
        raise ListError("This URL is not a Stremio addon manifest.")
    catalogs = [
        c for c in data["catalogs"]
        if c.get("type") in STREMIO_TYPES and c.get("id")
        and not c.get("extraRequired") and not any(e.get("isRequired") for e in c.get("extra") or [])
    ]
    names = [c.get("name") or c["id"] for c in catalogs]
    return [
        (f"{c['type']}/{c['id']}",
         f"{name} ({'movies' if c['type'] == 'movie' else 'shows'})" if names.count(name) > 1 else name)
        for c, name in zip(catalogs, names)
    ]


def _stremio_item(meta: dict, kind: str) -> ListItem:
    meta_id = str(meta.get("id") or "")
    return ListItem(
        kind=kind,
        title=meta.get("name") or "",
        year=_year(meta.get("releaseInfo") or meta.get("year")),
        tmdb_id=_str(meta.get("moviedb_id")),
        imdb_id=_str(meta.get("imdb_id")) or (meta_id if meta_id.startswith("tt") else None),
        tvdb_id=_str(meta.get("tvdb_id")),
    )


def _fetch_stremio(ref: ListRef, client: httpx.Client) -> FetchedList:
    manifest, _, catalog = ref.path.partition("#")
    stremio_type, _, catalog_id = catalog.partition("/")
    secrets = stremio_secrets(manifest)
    names = dict(stremio_catalogs(client, manifest))
    base = f"{manifest.removesuffix('/manifest.json')}/catalog/{stremio_type}/{quote(catalog_id, safe='')}"
    items: list[ListItem] = []
    previous_first = None
    for page in range(STREMIO_MAX_PAGES):
        url = f"{base}.json" if page == 0 else f"{base}/skip={len(items)}.json"
        data = _get(client, url, secrets, "Stremio addon")
        metas = data.get("metas") if isinstance(data, dict) else None
        if not isinstance(metas, list):
            raise ListError("The addon did not send a catalog.")
        # An addon that doesn't page sends the first page again.
        if not metas or metas[0].get("id") == previous_first:
            break
        previous_first = metas[0].get("id")
        items += [_stremio_item(meta, STREMIO_TYPES[stremio_type]) for meta in metas]
        if len(items) >= MAX_TITLES:
            break
    return FetchedList(names.get(catalog, catalog_id), list(dict.fromkeys(items)))


def tmdb_auth(key: str) -> dict:
    """A v4 read access token goes in a header, a v3 API key in the query."""
    if key.startswith("eyJ"):
        return {"headers": {"Authorization": f"Bearer {key}"}}
    return {"params": {"api_key": key}}


def _tmdb_item(row: dict, default_kind: str) -> ListItem:
    media = row.get("media_type") or default_kind
    kind = "show" if media == "tv" else "movie"
    return ListItem(
        kind=kind,
        title=row.get("title") or row.get("name") or "",
        year=_year(row.get("release_date") or row.get("first_air_date")),
        tmdb_id=_str(row.get("id")),
    )


def _fetch_tmdb(ref: ListRef, client: httpx.Client, key: str) -> FetchedList:
    auth = tmdb_auth(key)
    params = dict(auth.get("params", {}))
    headers = auth.get("headers", {})
    url = f"{TMDB_API}/{ref.path}"

    if ref.path.startswith("collection/"):
        data = _get(client, url, [key], params=params, headers=headers)
        parts = sorted(data.get("parts", []), key=lambda p: p.get("release_date") or "9999")
        return FetchedList(data.get("name") or ref.name, [_tmdb_item(p, "movie") for p in parts])

    default_kind = "tv" if "/tv" in f"/{ref.path}" else "movie"
    name, items = ref.name, []
    for page in range(1, TMDB_MAX_PAGES + 1):
        data = _get(client, url, [key], params={**params, "page": page}, headers=headers)
        if ref.path.startswith("list/"):
            name = data.get("name") or name
            rows = data.get("items", [])
        else:
            rows = data.get("results", [])
        items += [_tmdb_item(row, default_kind) for row in rows]
        if page >= (data.get("total_pages") or 1):
            break
    return FetchedList(name, items)


def check_tmdb_key(client: httpx.Client, key: str) -> str | None:
    """None when TMDB accepts the key, else the error."""
    auth = tmdb_auth(key)
    try:
        _get(client, f"{TMDB_API}/configuration", [key], **auth)
    except ListError as exc:
        return str(exc)
    return None
