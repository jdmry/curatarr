import sqlite3

from fastapi import APIRouter, Depends, Request

from app.plex import client as plex
from app.scope import list_scope
from app.web.deps import get_db, render

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return render(
        request,
        "index.html",
        active="dashboard",
        page="dashboard",
        plex_configured=plex.load_connection(db) is not None,
        logs=request.app.state.events.tail(80),
    )


@router.get("/dashboard/recap")
def dashboard_recap(request: Request, db: sqlite3.Connection = Depends(get_db)):
    entries = list_scope(db)
    context = {
        "scope_libraries": sum(1 for e in entries if e.is_library),
        "scope_collections": sum(1 for e in entries if not e.is_library),
        "last_run": db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone(),
    }
    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "partials/dashboard_recap.html", error="Plex is not configured.", **context)
    try:
        server_name, version, libraries = plex.cached_overview(connection)
    except Exception as exc:
        plex.forget_server()
        return render(request, "partials/dashboard_recap.html", error=plex.describe_error(exc, connection), **context)
    return render(
        request,
        "partials/dashboard_recap.html",
        server_name=server_name,
        version=version,
        movies=sum(lib.size for lib in libraries if lib.type == "movie"),
        shows=sum(lib.size for lib in libraries if lib.type == "show"),
        **context,
    )
