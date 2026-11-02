import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.plex import client as plex
from app.lists.store import list_lists
from app.posters.sources import get_default_source, list_sources
from app.scope import ScopeEntry, list_scope, set_scope_entry
from app.web.deps import get_db, render

router = APIRouter()


def _source_context(db: sqlite3.Connection) -> dict:
    return {"sources": list_sources(db), "default_source": get_default_source(db)}


@router.get("/posters/scope")
def scope_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    """Posters are for the collections made by lists: one row each, grouped by library."""
    hidden = plex.hidden_libraries(db)
    selected = {e.collection_key: e for e in list_scope(db) if not e.is_library}
    groups: dict[str, list] = {}
    for config in list_lists(db):
        if not config.collection_key or config.library_key in hidden:
            continue
        entry = selected.get(config.collection_key) or ScopeEntry(
            config.library_key, config.library_title, config.collection_key, config.name)
        groups.setdefault(config.library_title, []).append((entry, config.collection_key in selected, config))
    return render(request, "posters/scope.html", active="posters", page="posters/scope", groups=groups,
                  **_source_context(db))


@router.post("/posters/scope/entry")
def update_entry(
    request: Request,
    library_key: str = Form(...),
    library_title: str = Form(...),
    collection_key: str = Form(""),
    collection_title: str = Form(""),
    enabled: str = Form(""),
    source_id: str = Form(""),
    refresh_posters: str = Form(""),
    count: str = Form(""),
    db: sqlite3.Connection = Depends(get_db),
):
    if not any(c.collection_key == collection_key for c in list_lists(db) if c.collection_key):
        raise HTTPException(400, "Only collections made by your lists get posters.")
    entry = ScopeEntry(
        library_key, library_title, collection_key, collection_title, int(source_id) if source_id.isdigit() else None,
        bool(refresh_posters),
    )
    set_scope_entry(db, entry, bool(enabled))
    return render(request, "scope/row.html", entry=entry, enabled=bool(enabled), count=count,
                  **_source_context(db))
