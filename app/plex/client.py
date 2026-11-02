"""Connection to the Plex server."""

import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from plexapi.exceptions import Unauthorized
from plexapi.server import PlexServer

from app.secrets import mask
from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

TIMEOUT = 15


@dataclass(frozen=True)
class PlexConnection:
    url: str
    token: str


@dataclass
class Library:
    key: str
    title: str
    type: str
    size: int


@dataclass
class ConnectionCheck:
    ok: bool
    error: str | None = None
    server_name: str = ""
    version: str = ""
    libraries: list[Library] = field(default_factory=list)
    recent_thumbs: list[tuple[str, str]] = field(default_factory=list)  # (title, thumb path)




def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


HIDDEN_LIBRARIES = "plex.hidden_libraries"


def hidden_libraries(conn: sqlite3.Connection) -> set[str]:
    """Keys of the libraries left out of the app (Settings → Plex)."""
    return set(get_setting(conn, HIDDEN_LIBRARIES, []))


def visible(conn: sqlite3.Connection, libraries: list) -> list:
    hidden = hidden_libraries(conn)
    return [lib for lib in libraries if str(lib.key) not in hidden]


def load_connection(conn: sqlite3.Connection) -> PlexConnection | None:
    url, token = get_setting(conn, "plex.url"), get_setting(conn, "plex.token")
    return PlexConnection(url, token) if url and token else None


def save_connection(conn: sqlite3.Connection, url: str, token: str) -> None:
    set_setting(conn, "plex.url", normalize_url(url))
    set_setting(conn, "plex.token", token.strip())


def connect(connection: PlexConnection) -> PlexServer:
    return PlexServer(connection.url, connection.token, timeout=TIMEOUT)


_server_lock = threading.Lock()
_server: tuple[PlexConnection, PlexServer] | None = None


def get_server(connection: PlexConnection) -> PlexServer:
    """Reuse one PlexServer per saved connection (connecting costs a request)."""
    global _server
    with _server_lock:
        if _server is None or _server[0] != connection:
            _server = (connection, connect(connection))
        return _server[1]


def forget_server() -> None:
    global _server
    with _server_lock:
        _server = None
    forget_overview()


def library_sizes(server: PlexServer) -> list[Library]:
    """Movie and show libraries with their size (one request each, in parallel)."""
    sections = [s for s in server.library.sections() if s.type in ("movie", "show")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda s: Library(str(s.key), s.title, s.type, s.totalSize), sections))


OVERVIEW_TTL = 300
_overview_lock = threading.Lock()
_overview: tuple[float, PlexConnection, tuple[str, str, list[Library]]] | None = None


def cached_overview(connection: PlexConnection) -> tuple[str, str, list[Library]]:
    """(server name, version, libraries), kept a few minutes so the dashboard opens instantly."""
    global _overview
    with _overview_lock:
        if _overview and _overview[1] == connection and time.monotonic() - _overview[0] < OVERVIEW_TTL:
            return _overview[2]
    server = get_server(connection)
    result = (server.friendlyName, server.version, library_sizes(server))
    with _overview_lock:
        _overview = (time.monotonic(), connection, result)
    return result


def forget_overview() -> None:
    global _overview
    with _overview_lock:
        _overview = None


def describe_error(exc: Exception, connection: PlexConnection) -> str:
    if isinstance(exc, Unauthorized):
        return "Plex refused the token (401 Unauthorized)."
    if isinstance(exc, requests.exceptions.SSLError):
        return f"SSL error while connecting to {connection.url}. Try http:// instead of https://."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Could not reach {connection.url}. Check the address and that the server is running."
    if isinstance(exc, requests.exceptions.Timeout):
        return f"{connection.url} did not answer within {TIMEOUT} s."
    return mask(f"{type(exc).__name__}: {exc}", [connection.token])


def check_connection(connection: PlexConnection, with_thumbs: bool = False) -> ConnectionCheck:
    if not connection.url.startswith(("http://", "https://")):
        return ConnectionCheck(False, "The URL must start with http:// or https://.")
    try:
        server = connect(connection)
        libraries = [
            Library(str(s.key), s.title, s.type, s.totalSize)
            for s in server.library.sections()
            if s.type in ("movie", "show")
        ]
        check = ConnectionCheck(True, server_name=server.friendlyName, version=server.version, libraries=libraries)
        if with_thumbs and libraries:
            section = server.library.sectionByID(int(libraries[0].key))
            check.recent_thumbs = [(i.title, i.thumb) for i in section.recentlyAdded(maxresults=6) if i.thumb]
        return check
    except Exception as exc:
        log.info("Plex connection check failed: %s", describe_error(exc, connection))
        return ConnectionCheck(False, describe_error(exc, connection))
