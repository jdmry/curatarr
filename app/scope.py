"""What gets posters: the collections of the lists that have a poster service."""

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
        "SELECT library_key, library_title, collection_key, name, poster_source_id FROM lists"
        " WHERE posters = 1 AND collection_key IS NOT NULL ORDER BY position, id"
    )
    return [ScopeEntry(*row) for row in rows]
