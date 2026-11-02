"""Setup banners shown at the top of pages until something is configured."""

from dataclasses import dataclass
from pathlib import Path

from app.db import connection
from app.plex.client import load_connection


@dataclass(frozen=True)
class Banner:
    message: str
    href: str
    action: str


def banners_for(db_path: Path, page: str) -> list[Banner]:
    with connection(db_path) as conn:
        result = []
        if page != "settings/plex" and load_connection(conn) is None:
            result.append(Banner("Connect your Plex server to get started.", "/settings/plex", "Connect Plex"))
        if page.startswith("posters"):
            if conn.execute("SELECT 1 FROM poster_sources LIMIT 1").fetchone() is None:
                result.append(Banner("Add a poster service: it's where posters come from.",
                                     "/settings/services/new", "Add a poster service"))
            elif page == "posters/sync" and conn.execute("SELECT 1 FROM scope LIMIT 1").fetchone() is None:
                result.append(Banner("No collection is picked yet. Choose the collections that get posters.",
                                     "/posters/scope", "Choose collections"))
        return result
