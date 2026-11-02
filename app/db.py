"""SQLite storage: one short-lived connection per unit of work."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def open_db(path: Path) -> sqlite3.Connection:
    # FastAPI may open a request's connection in one worker thread and close it
    # in another. Each connection is still used by one request at a time.
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Connection that commits on success and rolls back on error."""
    conn = open_db(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate(path: Path) -> int:
    """Apply migrations/NNN_*.sql newer than the database. Returns the version."""
    conn = open_db(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            number = int(file.name.split("_", 1)[0])
            if number > version:
                conn.executescript(f"BEGIN;\n{file.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;")
                version = number
        return version
    finally:
        conn.close()
