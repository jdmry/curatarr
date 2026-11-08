"""Which titles of a list are in a Plex library."""

import sqlite3
from dataclasses import dataclass, field

from app.lists.sources import ListItem
from app.plex.guid_index import find


@dataclass
class Match:
    owned: list[tuple[ListItem, str]] = field(default_factory=list)  # (title, rating key), in list order
    missing: list[ListItem] = field(default_factory=list)
    ranked: list[tuple[ListItem, str | None]] = field(default_factory=list)  # both, in list order (None = missing)
    other_kind: int = 0  # shows in a movie library or the reverse, left out

    @property
    def total(self) -> int:
        return len(self.owned) + len(self.missing)


def match(conn: sqlite3.Connection, library_key: str, library_type: str, items: list[ListItem]) -> Match:
    kind = "movie" if library_type == "movie" else "show"
    wanted = [item for item in items if item.kind == kind]
    found = find(conn, library_key, sorted({guid for item in wanted for guid in item.guids}))
    result = Match(other_kind=len(items) - len(wanted))
    seen = set()
    for item in wanted:
        rating_key = next((found[guid] for guid in item.guids if guid in found), None)
        if rating_key is None:
            result.missing.append(item)
            result.ranked.append((item, None))
        elif rating_key not in seen:
            seen.add(rating_key)
            result.owned.append((item, rating_key))
            result.ranked.append((item, rating_key))
    return result
