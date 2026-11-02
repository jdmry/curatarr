import sqlite3

from fastapi import APIRouter, Depends, Form, Request

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
    return render(request, "posters/scope.html", active="posters", page="posters/scope", entries=list_scope(db))


@router.get("/posters/scope/libraries")
def scope_libraries(request: Request, db: sqlite3.Connection = Depends(get_db)):
    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "scope/libraries.html", error="Plex is not configured.")
    try:
        libraries = [s for s in plex.get_server(connection).library.sections() if s.type in ("movie", "show")]
    except Exception as exc:
        plex.forget_server()
        return render(request, "scope/libraries.html", error=plex.describe_error(exc, connection))

    entries = list_scope(db)
    selected = {(e.library_key, e.collection_key): e for e in entries}
    collection_counts = {}
    for entry in entries:
        if not entry.is_library:
            collection_counts[entry.library_key] = collection_counts.get(entry.library_key, 0) + 1
    return render(
        request,
        "scope/libraries.html",
        libraries=libraries,
        selected=selected,
        collection_counts=collection_counts,
        **_source_context(db),
    )


@router.get("/posters/scope/libraries/{library_key}/collections")
def scope_collections(request: Request, library_key: str, db: sqlite3.Connection = Depends(get_db)):
    connection = plex.load_connection(db)
    try:
        section = plex.get_server(connection).library.sectionByID(int(library_key))
        collections = section.collections()
    except Exception as exc:
        plex.forget_server()
        return render(request, "scope/collections.html", error=plex.describe_error(exc, connection))
    selected = {e.collection_key: e for e in list_scope(db) if e.library_key == library_key and not e.is_library}
    linked = {c.collection_key for c in list_lists(db) if c.collection_key}
    collections.sort(key=lambda c: (str(c.ratingKey) not in selected, c.title.casefold()))
    return render(
        request,
        "scope/collections.html",
        section=section,
        collections=collections,
        selected=selected,
        linked_keys=linked,
        **_source_context(db),
    )


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
    linked: str = Form(""),
    count: str = Form(""),
    db: sqlite3.Connection = Depends(get_db),
):
    entry = ScopeEntry(
        library_key, library_title, collection_key, collection_title, int(source_id) if source_id.isdigit() else None,
        bool(linked and refresh_posters),
    )
    set_scope_entry(db, entry, bool(enabled))
    return render(request, "scope/row.html", entry=entry, enabled=bool(enabled), count=count, linked=bool(linked),
                  **_source_context(db))
