"""Lists saved in the database."""

import sqlite3
from dataclasses import dataclass, fields

PLACEMENTS = {
    "home": "Home and Recommended",
    "recommended": "Recommended only",
    "library": "Library only",
}


@dataclass
class ListConfig:
    id: int | None
    name: str
    url: str
    library_key: str
    library_title: str
    placement: str = "home"
    max_items: int = 50
    position: int = 0
    enabled: bool = True
    collection_key: str | None = None
    synced_at: str | None = None
    last_total: int | None = None
    last_matched: int | None = None
    last_error: str | None = None
    audience: str = "all"  # all, owner, or a Plex user id
    audience_name: str = ""

    @property
    def private(self) -> bool:
        return self.audience != "all"


_COLUMNS = [f.name for f in fields(ListConfig)]
_EDITABLE = ("name", "url", "library_key", "library_title", "placement", "max_items", "enabled", "audience",
             "audience_name")


def _row(row: sqlite3.Row) -> ListConfig:
    values = {name: row[name] for name in _COLUMNS}
    values["enabled"] = bool(values["enabled"])
    return ListConfig(**values)


def list_lists(conn: sqlite3.Connection) -> list[ListConfig]:
    rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lists ORDER BY position, id")
    return [_row(row) for row in rows]


def get_list(conn: sqlite3.Connection, list_id: int) -> ListConfig | None:
    row = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM lists WHERE id = ?", (list_id,)).fetchone()
    return _row(row) if row else None


def save_list(conn: sqlite3.Connection, config: ListConfig) -> int:
    values = [getattr(config, name) for name in _EDITABLE]
    if config.id is None:
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM lists").fetchone()[0]
        cursor = conn.execute(
            f"INSERT INTO lists ({', '.join(_EDITABLE)}, position) VALUES ({', '.join('?' * len(_EDITABLE))}, ?)",
            (*values, position),
        )
        return cursor.lastrowid
    conn.execute(
        f"UPDATE lists SET {', '.join(f'{name} = ?' for name in _EDITABLE)}, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        (*values, config.id),
    )
    return config.id


def delete_list(conn: sqlite3.Connection, list_id: int) -> None:
    conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
