"""Poster sources: a URL template plus a few options, stored in the database."""

import json
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.posters.postersplus import NO_QUALITY, adapt_for_plex, is_postersplus
from app.posters.rpdb import is_rpdb, key_of
from app.posters.template import Rendered, TypeNames, placeholders, render, title_values, unknown_placeholders
from app.secrets import MASK, is_secret_name, mask, secrets_in_url
from app.titles import TitleInfo

ID_PLACEHOLDERS = {"imdb_id", "tmdb_id", "tvdb_id", "id"}
DEFAULT_TIMEOUT = 120
KINDS = {"postersplus": "PostersPlus", "rpdb": "RPDB", "generic": "Other image URL"}


@dataclass
class PosterSource:
    id: int | None
    name: str
    url_template: str
    kind: str = "generic"
    type_movie: str = "movie"
    type_show: str = "series"
    no_quality: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = DEFAULT_TIMEOUT
    revision: int = 1
    is_default: bool = False
    read_quality: bool = True

    @property
    def uses_quality(self) -> bool:
        """Whether quality must be read from the files (it costs a Plex request per title)."""
        return self.read_quality and "quality" in placeholders(self.url_template)

    @property
    def host(self) -> str:
        return urlsplit(self.url_template).hostname or ""

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, KINDS["generic"])

    @property
    def url_secrets(self) -> list[str]:
        return [*secrets_in_url(self.url_template), key_of(self.url_template)]

    @property
    def secrets(self) -> list[str]:
        return [*self.url_secrets, *(v for v in self.headers.values() if v)]

    @property
    def masked_template(self) -> str:
        return mask(self.url_template, self.url_secrets)

    def render(self, info: TitleInfo) -> Rendered:
        types = TypeNames(movie=self.type_movie, show=self.type_show)
        return render(self.url_template, title_values(info, types, self.no_quality))


@dataclass
class Analysis:
    template: str = ""
    kind: str = "generic"
    changes: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    secret_params: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def default_name(self) -> str:
        if self.kind in ("postersplus", "rpdb"):
            return KINDS[self.kind]
        return urlsplit(self.template).hostname or "Poster source"


def _params(template: str) -> list[tuple[str, str]]:
    query = template.partition("?")[2].partition("#")[0]
    return [(p.partition("=")[0], p.partition("=")[2]) for p in query.split("&") if p]


def analyze(raw: str) -> Analysis:
    """Understand a pasted URL: which service, which placeholders, what we adjust."""
    raw = raw.strip()
    if not raw:
        return Analysis(error="Paste a poster URL.")
    if not raw.startswith(("http://", "https://")):
        return Analysis(error="The URL must start with http:// or https://.")

    analysis = Analysis(template=raw)
    if is_postersplus(raw):
        analysis.kind = "postersplus"
        analysis.template, analysis.changes = adapt_for_plex(raw)
    elif is_rpdb(raw):
        analysis.kind = "rpdb"

    analysis.variables = list(dict.fromkeys(placeholders(analysis.template)))
    analysis.unknown = list(dict.fromkeys(unknown_placeholders(analysis.template)))
    analysis.secret_params = [name for name, value in _params(analysis.template) if value and is_secret_name(name)]
    if analysis.kind == "rpdb":
        analysis.secret_params.insert(0, "API key")
    if analysis.unknown:
        analysis.warnings.append(
            "Unknown placeholders: " + ", ".join(f"{{{n}}}" for n in analysis.unknown) + ". They are left as-is."
        )
    if not ID_PLACEHOLDERS & set(analysis.variables):
        analysis.warnings.append("No id placeholder ({imdb_id}, {tmdb_id}…): every title would get the same image.")
    return analysis


def restore_secrets(new: str, old: str) -> str:
    """Put back secret values that the edit form showed as ***."""
    old_values = dict(_params(old))
    base, sep, rest = new.partition("?")
    if not sep:
        return new
    query, hash_sep, fragment = rest.partition("#")
    params = []
    for param in query.split("&"):
        name, eq, value = param.partition("=")
        if value == MASK and name in old_values:
            param = f"{name}={old_values[name]}"
        params.append(param)
    return f"{base}?{'&'.join(params)}{hash_sep}{fragment}"


def parse_headers(text: str) -> dict[str, str]:
    headers = {}
    for line in text.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip():
            headers[name.strip()] = value.strip()
    return headers


def format_headers(headers: dict[str, str], masked: bool = True) -> str:
    return "\n".join(f"{name}: {MASK if masked and value else value}" for name, value in headers.items())


def restore_headers(new: dict[str, str], old: dict[str, str]) -> dict[str, str]:
    return {name: old.get(name, value) if value == MASK else value for name, value in new.items()}


# Storage

_RENDER_FIELDS = ("url_template", "type_movie", "type_show", "no_quality", "headers", "read_quality")


def _from_row(row: sqlite3.Row) -> PosterSource:
    return PosterSource(
        id=row["id"], name=row["name"], url_template=row["url_template"], kind=row["kind"],
        type_movie=row["type_movie"], type_show=row["type_show"], no_quality=row["no_quality"],
        headers=json.loads(row["headers"]), timeout=row["timeout"], revision=row["revision"],
        is_default=bool(row["is_default"]), read_quality=bool(row["read_quality"]),
    )


def list_sources(conn: sqlite3.Connection) -> list[PosterSource]:
    rows = conn.execute("SELECT * FROM poster_sources ORDER BY is_default DESC, name COLLATE NOCASE")
    return [_from_row(row) for row in rows]


def get_source(conn: sqlite3.Connection, source_id: int) -> PosterSource | None:
    row = conn.execute("SELECT * FROM poster_sources WHERE id = ?", (source_id,)).fetchone()
    return _from_row(row) if row else None


def get_default_source(conn: sqlite3.Connection) -> PosterSource | None:
    row = conn.execute("SELECT * FROM poster_sources WHERE is_default = 1").fetchone()
    return _from_row(row) if row else None


def save_source(conn: sqlite3.Connection, source: PosterSource) -> int:
    """Insert or update. The revision goes up when the rendered poster may change."""
    values = (
        source.name, source.url_template, source.kind, source.type_movie, source.type_show,
        source.no_quality, json.dumps(source.headers), source.timeout, int(source.read_quality),
    )
    if source.id is None:
        cursor = conn.execute(
            "INSERT INTO poster_sources (name, url_template, kind, type_movie, type_show, no_quality, headers, timeout,"
            " read_quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        source_id = cursor.lastrowid
    else:
        old = get_source(conn, source.id)
        changed = any(getattr(old, f) != getattr(source, f) for f in _RENDER_FIELDS) if old else False
        conn.execute(
            "UPDATE poster_sources SET name = ?, url_template = ?, kind = ?, type_movie = ?, type_show = ?,"
            " no_quality = ?, headers = ?, timeout = ?, read_quality = ?, revision = revision + ?,"
            " updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (*values, int(changed), source.id),
        )
        source_id = source.id
    if get_default_source(conn) is None:
        set_default_source(conn, source_id)
    return source_id


def set_default_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("UPDATE poster_sources SET is_default = (id = ?)", (source_id,))


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM poster_sources WHERE id = ?", (source_id,))
    if get_default_source(conn) is None:
        row = conn.execute("SELECT id FROM poster_sources ORDER BY id LIMIT 1").fetchone()
        if row:
            set_default_source(conn, row["id"])
