import sqlite3

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.lists.sources import check_mdblist_key, check_tmdb_key
from app.plex import client as plex
from app.settings_store import get_setting, set_setting
from app.web.deps import get_db, render

router = APIRouter()


@router.get("/settings")
def settings_root():
    return RedirectResponse("/settings/plex", status_code=303)


@router.get("/settings/plex")
def settings_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    saved = plex.load_connection(db)
    return render(request, "settings/plex.html", active="settings", page="settings/plex", plex_url=saved.url if saved else "", has_token=bool(saved))


def _form_connection(db: sqlite3.Connection, url: str, token: str) -> plex.PlexConnection:
    """Connection from the form; an empty token means "keep the saved one"."""
    saved = plex.load_connection(db)
    if not token.strip() and saved:
        token = saved.token
    return plex.PlexConnection(plex.normalize_url(url), token.strip())


@router.post("/settings/plex/test")
def test_plex(request: Request, url: str = Form(""), token: str = Form(""), db: sqlite3.Connection = Depends(get_db)):
    connection = _form_connection(db, url, token)
    is_saved = connection == plex.load_connection(db)
    check = plex.check_connection(connection, with_thumbs=is_saved)
    return render(request, "partials/plex_check.html", check=check, saved=False)


@router.post("/settings/plex")
def save_plex(request: Request, url: str = Form(""), token: str = Form(""), db: sqlite3.Connection = Depends(get_db)):
    connection = _form_connection(db, url, token)
    if not connection.url or not connection.token:
        check = plex.ConnectionCheck(False, "Both the server URL and the token are required.")
        return render(request, "partials/plex_check.html", check=check, saved=False)
    plex.save_connection(db, connection.url, connection.token)
    plex.forget_server()
    check = plex.check_connection(connection, with_thumbs=True)
    return render(request, "partials/plex_check.html", check=check, saved=True)


@router.get("/settings/tmdb")
def tmdb_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    has_key = bool(get_setting(db, "tmdb.key"))
    return render(request, "settings/tmdb.html", active="settings", page="settings/tmdb", has_key=has_key)


@router.post("/settings/tmdb")
def save_tmdb(request: Request, key: str = Form(""), db: sqlite3.Connection = Depends(get_db)):
    """An empty field keeps the saved key."""
    key = key.strip() or get_setting(db, "tmdb.key") or ""
    if not key:
        return render(request, "partials/tmdb_check.html", error="Paste your TMDB API key.")
    with httpx.Client(follow_redirects=True) as client:
        error = check_tmdb_key(client, key)
    if error is None:
        set_setting(db, "tmdb.key", key)
    return render(request, "partials/tmdb_check.html", error=error)


@router.get("/settings/mdblist")
def mdblist_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return render(request, "settings/mdblist.html", active="settings", page="settings/mdblist",
                  has_key=bool(get_setting(db, "mdblist.key")), username=get_setting(db, "mdblist.user"))


@router.post("/settings/mdblist")
def save_mdblist(request: Request, key: str = Form(""), db: sqlite3.Connection = Depends(get_db)):
    """An empty field keeps the saved key."""
    key = key.strip() or get_setting(db, "mdblist.key") or ""
    if not key:
        return render(request, "partials/mdblist_check.html", error="Paste your MDBList API key.")
    with httpx.Client(follow_redirects=True) as client:
        username, error = check_mdblist_key(client, key)
    if error is None:
        set_setting(db, "mdblist.key", key)
        set_setting(db, "mdblist.user", username)
    return render(request, "partials/mdblist_check.html", error=error, username=username)
