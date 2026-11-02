"""What to sync: whole libraries and/or specific collections, each with a source."""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeEntry:
    library_key: str
    library_title: str
    collection_key: str = ""
    collection_title: str = ""
    source_id: int | None = None

    @property
    def is_library(self) -> bool:
        return not self.collection_key


def list_scope(conn: sqlite3.Connection) -> list[ScopeEntry]:
    rows = conn.execute(
        "SELECT library_key, library_title, collection_key, collection_title, source_id FROM scope"
        " ORDER BY library_title COLLATE NOCASE, collection_key != '', collection_title COLLATE NOCASE"
    )
    return [ScopeEntry(*row) for row in rows]


def set_scope_entry(conn: sqlite3.Connection, entry: ScopeEntry, enabled: bool) -> None:
    if not enabled:
        conn.execute(
            "DELETE FROM scope WHERE library_key = ? AND collection_key = ?", (entry.library_key, entry.collection_key)
        )
        return
    conn.execute(
        "INSERT INTO scope (library_key, library_title, collection_key, collection_title, source_id)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (library_key, collection_key) DO UPDATE SET"
        " library_title = excluded.library_title, collection_title = excluded.collection_title,"
        " source_id = excluded.source_id",
        (entry.library_key, entry.library_title, entry.collection_key, entry.collection_title, entry.source_id),
    )
