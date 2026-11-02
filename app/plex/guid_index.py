"""IMDb, TMDB and TVDB ids of a Plex library, to find a list's titles in it.

Plex can't search by these ids, so they are kept in SQLite: a full pass a day
(about a minute for 50,000 titles) and the newly added titles in between.
"""

import logging
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from app import db

log = logging.getLogger(__name__)

PAGE = 5000
QUERY_TIMEOUT = 120
FULL_EVERY = 86400
CHECK_EVERY = 600
# addedAt has a one second resolution and the clocks may differ a little.
OVERLAP = 300

_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


def _plex_type(section) -> int:
    return 1 if section.type == "movie" else 2


def _scan(server, section, since: int | None = None) -> Iterator[tuple[str, str]]:
    """(guid, rating key) pairs of the library, or of the titles added since a time."""
    path = f"/library/sections/{section.key}/all?type={_plex_type(section)}&includeGuids=1"
    if since is not None:
        path += f"&addedAt>>={since}"
    start = 0
    while True:
        headers = {"X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(PAGE)}
        items = list(server.query(path, headers=headers, timeout=QUERY_TIMEOUT))
        for item in items:
            for guid in item.findall("Guid"):
                yield guid.get("id"), item.get("ratingKey")
        if len(items) < PAGE:
            return
        start += PAGE


def _build(conn: sqlite3.Connection, server, section, now: int) -> None:
    key = str(section.key)
    pairs = list(_scan(server, section))
    conn.execute("DELETE FROM plex_guids WHERE library_key = ?", (key,))
    conn.executemany(
        "INSERT OR REPLACE INTO plex_guids (library_key, guid, rating_key) VALUES (?, ?, ?)",
        ((key, guid, rating_key) for guid, rating_key in pairs),
    )
    conn.execute(
        "INSERT OR REPLACE INTO plex_index (library_key, built_at, checked_at, size) VALUES (?, ?, ?, ?)",
        (key, now, now, len({rating_key for _, rating_key in pairs})),
    )
    conn.commit()


def _build_in_background(db_path: Path, server, section) -> None:
    key = str(section.key)
    if not _locks[key].acquire(blocking=False):
        return  # already being built

    def run():
        try:
            with db.connection(db_path) as conn:
                _build(conn, server, section, int(time.time()))
        except Exception:
            log.exception("Indexing library %s failed", section.title)
        finally:
            _locks[key].release()

    threading.Thread(target=run, name=f"index-{key}", daemon=True).start()


def building(library_key: str) -> bool:
    return _locks[str(library_key)].locked()


def ensure_index(
    conn: sqlite3.Connection, server, section, now: float | None = None, background: Path | None = None
) -> bool:
    """Build the index of a library, or add the titles added since the last check.

    A full build takes a minute or two on big libraries. With `background` (the
    database path), it runs in a thread instead and False means "not ready yet";
    a stale index stays usable meanwhile.
    """
    key = str(section.key)
    now = int(now or time.time())
    row = conn.execute("SELECT built_at, checked_at FROM plex_index WHERE library_key = ?", (key,)).fetchone()
    if row is None or now - row["built_at"] > FULL_EVERY:
        if background is not None:
            _build_in_background(background, server, section)
            return row is not None
        with _locks[key]:
            _build(conn, server, section, now)
        return True
    if now - row["checked_at"] > CHECK_EVERY:
        if not _locks[key].acquire(blocking=background is None):
            return True  # a full build is running: the current index will do
        try:
            pairs = list(_scan(server, section, since=row["checked_at"] - OVERLAP))
            conn.executemany(
                "INSERT OR REPLACE INTO plex_guids (library_key, guid, rating_key) VALUES (?, ?, ?)",
                ((key, guid, rating_key) for guid, rating_key in pairs),
            )
            conn.execute("UPDATE plex_index SET checked_at = ? WHERE library_key = ?", (now, key))
            conn.commit()
        finally:
            _locks[key].release()
    return True


def forget_index(conn: sqlite3.Connection, library_key: str) -> None:
    """Rebuild from scratch next time, e.g. after a title in it was not found."""
    conn.execute("DELETE FROM plex_index WHERE library_key = ?", (library_key,))


def find(conn: sqlite3.Connection, library_key: str, guids: list[str]) -> dict[str, str]:
    """Rating key of each guid found in the library."""
    found = {}
    for start in range(0, len(guids), 500):
        chunk = guids[start:start + 500]
        rows = conn.execute(
            f"SELECT guid, rating_key FROM plex_guids WHERE library_key = ? AND guid IN ({','.join('?' * len(chunk))})",
            (library_key, *chunk),
        )
        found.update((row["guid"], row["rating_key"]) for row in rows)
    return found
