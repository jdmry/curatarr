"""One title at a time: search it, preview its new poster, send it to Plex."""

import base64
import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from app.plex import client as plex
from app.plex import titles
from app.posters import fetch
from app.posters.sources import get_default_source, list_sources
from app.scope import list_scope
from app.secrets import mask
from app.sync.engine import fingerprint, remember, source_for, upload
from app.web.deps import get_db, render

router = APIRouter()


def search(request: Request, db: sqlite3.Connection, q: str, pick: str):
    """Title search shared by this page and the poster service form."""
    query = q.strip()
    context = {"pick": pick, "query": query}
    if len(query) < 2:
        return render(request, "partials/title_results.html", results=None, **context)
    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "partials/title_results.html", error="Plex is not configured.", results=[], **context)
    try:
        results = titles.search_titles(plex.get_server(connection), query)
    except Exception as exc:
        plex.forget_server()
        error = plex.describe_error(exc, connection)
        return render(request, "partials/title_results.html", error=error, results=[], **context)
    return render(request, "partials/title_results.html", results=results, **context)


@router.get("/posters/titles")
def titles_page(request: Request):
    return render(request, "posters/titles.html", active="posters", page="posters/titles")


@router.get("/posters/titles/search")
def find_titles(request: Request, q: str = "", db: sqlite3.Connection = Depends(get_db)):
    return search(request, db, q, "posters")


def _panel(request: Request, db: sqlite3.Connection, rating_key: int, source_id: int | None, apply: bool):
    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "partials/title_poster.html", error="Plex is not configured.")
    sources = {s.id: s for s in list_sources(db)}
    if not sources:
        return render(request, "partials/title_poster.html", error="Add a poster service first, in Settings.")
    try:
        item = plex.get_server(connection).fetchItem(rating_key)
    except Exception as exc:
        plex.forget_server()
        return render(request, "partials/title_poster.html", error=plex.describe_error(exc, connection))

    source = sources.get(source_id) or source_for(item, list_scope(db), sources, get_default_source(db))
    state = db.execute("SELECT applied_at FROM poster_state WHERE rating_key = ?", (str(item.ratingKey),)).fetchone()
    context = {
        "item": item, "source": source, "sources": list(sources.values()), "rating_key": rating_key,
        "library": getattr(item, "librarySectionTitle", ""), "applied_at": state["applied_at"] if state else None,
    }
    try:
        info = titles.title_info(item, with_quality=source.uses_quality)
    except Exception as exc:
        return render(request, "partials/title_poster.html", error=plex.describe_error(exc, connection), **context)
    context["info"] = info
    rendered = source.render(info)
    if rendered.url is None:
        return render(request, "partials/title_poster.html", skipped=rendered.skipped, **context)

    masked = mask(rendered.url, source.secrets)
    result = fetch.fetch_poster(rendered.url, source.headers, source.timeout, source.secrets)
    context.update(result=result, masked_url=masked)
    if not result.ok:
        return render(request, "partials/title_poster.html", **context)
    context["image"] = f"data:{result.content_type};base64,{base64.b64encode(result.content).decode()}"

    if apply:
        try:
            upload(item, result.content)
        except Exception as exc:
            reason = mask(f"Upload to Plex failed: {type(exc).__name__}: {exc}", source.secrets)
            request.app.state.events.add("error", f"{item.title}: {reason}")
            return render(request, "partials/title_poster.html", apply_error=reason, **context)
        remember(db, str(item.ratingKey), fingerprint(source, masked))
        quality = ",".join(info.quality) or "no quality"
        request.app.state.events.add("ok", f"{item.title}: poster updated from {source.name} ({quality}), by hand")
        context.update(applied=True, applied_at=None)
    return render(request, "partials/title_poster.html", **context)


@router.get("/posters/titles/{rating_key:int}")
def title_poster(request: Request, rating_key: int, source_id: int | None = None,
                 db: sqlite3.Connection = Depends(get_db)):
    return _panel(request, db, rating_key, source_id, apply=False)


@router.post("/posters/titles/{rating_key:int}/apply")
def apply_poster(request: Request, rating_key: int, source_id: int = Form(...),
                 db: sqlite3.Connection = Depends(get_db)):
    return _panel(request, db, rating_key, source_id, apply=True)
