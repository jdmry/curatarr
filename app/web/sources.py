import base64
import sqlite3
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.plex import client as plex
from app.plex import titles
from app.posters import fetch
from app.posters import rpdb
from app.posters.postersplus import NO_QUALITY
from app.posters.sources import (
    DEFAULT_TIMEOUT,
    KINDS,
    Analysis,
    PosterSource,
    analyze,
    delete_source,
    format_headers,
    get_source,
    list_sources,
    parse_headers,
    restore_headers,
    restore_secrets,
    save_source,
    set_default_source,
)
from app.posters.template import VARIABLES
from app.secrets import MASK, mask
from app.web.deps import get_db, render
from app.web.titles import search as title_search

router = APIRouter()


@dataclass
class SourceForm:
    url: str
    name: str
    type_movie: str
    type_show: str
    no_quality: str
    headers: str
    timeout: str
    editing_id: str
    read_quality: bool
    kind: str
    rpdb: rpdb.RpdbOptions


def source_form(
    url: str = Form(""),
    name: str = Form(""),
    type_movie: str = Form(""),
    type_show: str = Form(""),
    no_quality: str = Form(""),
    headers: str = Form(""),
    timeout: str = Form(""),
    editing_id: str = Form(""),
    read_quality: str = Form(""),
    kind: str = Form("generic"),
    rpdb_key: str = Form(""),
    rpdb_style: str = Form("poster-default"),
    rpdb_lang: str = Form(""),
    rpdb_size: str = Form("medium"),
    rpdb_fallback: str = Form(""),
) -> SourceForm:
    options = rpdb.RpdbOptions(rpdb_key.strip(), rpdb_style, rpdb_lang.strip(), rpdb_size, bool(rpdb_fallback))
    return SourceForm(url, name, type_movie, type_show, no_quality, headers, timeout, editing_id, bool(read_quality),
                      kind if kind in KINDS else "generic", options)


def _timeout(value: str) -> int:
    try:
        return max(5, min(int(value), 600))
    except ValueError:
        return DEFAULT_TIMEOUT


def build_source(db: sqlite3.Connection, form: SourceForm) -> tuple[PosterSource, Analysis]:
    """Source from the form, with *** secrets put back from the saved source."""
    existing = get_source(db, int(form.editing_id)) if form.editing_id.isdigit() else None
    if form.kind == "rpdb":
        if form.rpdb.key in ("", MASK) and existing:
            form.rpdb.key = rpdb.key_of(existing.url_template)
        raw = rpdb.build(form.rpdb)
    else:
        raw = restore_secrets(form.url, existing.url_template) if existing else form.url
    analysis = analyze(raw)
    if form.kind == "rpdb" and not form.rpdb.key:
        analysis.error = "Enter your RPDB API key."
    headers = parse_headers(form.headers)
    if existing:
        headers = restore_headers(headers, existing.headers)
    no_quality = form.no_quality.strip() or (NO_QUALITY if analysis.kind == "postersplus" else "")
    source = PosterSource(
        id=existing.id if existing else None,
        name=form.name.strip() or analysis.default_name,
        url_template=analysis.template,
        kind=analysis.kind,
        type_movie=form.type_movie.strip() or "movie",
        type_show=form.type_show.strip() or "series",
        no_quality=no_quality,
        headers=headers,
        timeout=_timeout(form.timeout),
        revision=existing.revision if existing else 1,
        is_default=existing.is_default if existing else False,
        read_quality=form.read_quality,
    )
    return source, analysis


def _form_page(request: Request, source: PosterSource, error: str | None = None, url: str | None = None):
    options = rpdb.parse(source.url_template) if rpdb.is_rpdb(source.url_template) else rpdb.RpdbOptions()
    if options.key:
        options.key = MASK
    return render(
        request,
        "sources/form.html",
        active="settings",
        page="settings/services",
        source=source,
        kind=source.kind,
        kinds=KINDS,
        rpdb_options=options,
        rpdb_styles=rpdb.STYLES,
        rpdb_sizes=rpdb.SIZES,
        url=source.masked_template if url is None else url,
        headers_text=format_headers(source.headers),
        variables=VARIABLES,
        error=error,
    )


@router.get("/settings/services")
def sources_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return render(request, "sources/index.html", active="settings", page="settings/services", sources=list_sources(db))


@router.get("/settings/services/new")
def new_source(request: Request, kind: str = ""):
    if kind not in KINDS:
        return render(request, "sources/pick.html", active="settings", page="settings/services", kinds=KINDS)
    return _form_page(request, PosterSource(id=None, name="", url_template="", kind=kind,
                                            read_quality=kind != "rpdb"))


@router.get("/settings/services/{source_id:int}")
def edit_source(request: Request, source_id: int, db: sqlite3.Connection = Depends(get_db)):
    source = get_source(db, source_id)
    if source is None:
        raise HTTPException(404)
    return _form_page(request, source)


def _save(request: Request, db: sqlite3.Connection, form: SourceForm):
    source, analysis = build_source(db, form)
    if form.kind == "rpdb":
        source.kind = "rpdb"
    if analysis.error:
        return _form_page(request, source, analysis.error, url=form.url)
    save_source(db, source)
    return RedirectResponse("/settings/services", status_code=303)


@router.post("/settings/services")
def create_source(request: Request, form: SourceForm = Depends(source_form), db: sqlite3.Connection = Depends(get_db)):
    form.editing_id = ""
    return _save(request, db, form)


@router.post("/settings/services/analyze")
def analyze_url(request: Request, url: str = Form("")):
    return render(request, "partials/source_analysis.html", analysis=analyze(url) if url.strip() else None)


@router.get("/settings/services/titles")
def find_titles(request: Request, q: str = "", db: sqlite3.Connection = Depends(get_db)):
    return title_search(request, db, q, "service")


@router.post("/settings/services/test")
def test_source(
    request: Request,
    rating_key: str = Form(...),
    form: SourceForm = Depends(source_form),
    db: sqlite3.Connection = Depends(get_db),
):
    source, analysis = build_source(db, form)
    context = {"source": source}
    if analysis.error:
        return render(request, "partials/source_test.html", error=analysis.error, **context)

    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "partials/source_test.html", error="Plex is not configured.", **context)
    try:
        item = plex.get_server(connection).fetchItem(int(rating_key))
        info = titles.title_info(item, with_quality=source.uses_quality)
    except Exception as exc:
        plex.forget_server()
        return render(request, "partials/source_test.html", error=plex.describe_error(exc, connection), **context)

    context.update(info=info, current_thumb=getattr(item, "thumb", None))
    rendered = source.render(info)
    if rendered.url is None:
        return render(request, "partials/source_test.html", skipped=rendered.skipped, **context)

    context["masked_url"] = mask(rendered.url, source.secrets)
    result = fetch.fetch_poster(rendered.url, source.headers, source.timeout, source.secrets)
    image = None
    if result.ok:
        image = f"data:{result.content_type};base64,{base64.b64encode(result.content).decode()}"
    return render(request, "partials/source_test.html", result=result, image=image, **context)


@router.post("/settings/services/{source_id:int}")
def update_source(
    request: Request,
    source_id: int,
    form: SourceForm = Depends(source_form),
    db: sqlite3.Connection = Depends(get_db),
):
    if get_source(db, source_id) is None:
        raise HTTPException(404)
    form.editing_id = str(source_id)
    return _save(request, db, form)


@router.post("/settings/services/{source_id:int}/default")
def make_default(source_id: int, db: sqlite3.Connection = Depends(get_db)):
    if get_source(db, source_id):
        set_default_source(db, source_id)
    return RedirectResponse("/settings/services", status_code=303)


@router.post("/settings/services/{source_id:int}/delete")
def remove_source(source_id: int, db: sqlite3.Connection = Depends(get_db)):
    delete_source(db, source_id)
    return RedirectResponse("/settings/services", status_code=303)
