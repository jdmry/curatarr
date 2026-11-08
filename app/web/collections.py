"""Collections: lists (MDBList, TMDB…) kept as Plex collections."""

import sqlite3
import time
from urllib.parse import quote
from dataclasses import dataclass

import httpx
from plexapi.exceptions import NotFound
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.lists import sources
from app.lists.collections import delete_collection, made_by
from app.lists.matching import match
from app.lists.store import PLACEMENTS, ListConfig, delete_list, get_list, list_lists, save_list
from app.plex import client as plex
from app.plex import sharing
from app.plex.guid_index import ensure_index
from app.posters.sources import get_default_source, list_sources
from app.secrets import MASK
from app.settings_store import get_setting
from app.sync.runner import AlreadyRunning
from app.sync.scheduler import DEFAULT_INTERVAL, INTERVALS, LISTS_SCHEDULE, load_schedule, save_schedule
from app.web.deps import get_db, render

router = APIRouter()

MISSING_POSTERS = 60  # TMDB lookups per preview for missing titles; the rest show their name


FRIENDS_TTL = 300
_friends_cache: tuple[float, list[tuple[str, str]]] | None = None


@dataclass
class ListForm:
    url: str
    name: str
    library_key: str
    placement: str
    max_items: int
    audience: str
    poster_source: str = ""  # "" for no posters, "default", or a service id


SOURCES = {"mdblist": "MDBList", "tmdb": "TMDB", "stremio": "Stremio addon"}


def source_fields(url: str) -> dict:
    """The form's source fields for a saved list (the opposite of list_url)."""
    fields = dict.fromkeys(("mdblist_list", "mdblist_url", "tmdb_preset", "tmdb_url", "stremio_manifest",
                            "stremio_catalog"), "")
    fields["source"] = "mdblist"
    if url.startswith("mdblist:"):
        fields["mdblist_list"] = url.removeprefix("mdblist:")
    elif url.startswith("tmdb:"):
        fields.update(source="tmdb", tmdb_preset=url.removeprefix("tmdb:"))
    elif "/manifest.json" in url:
        manifest, _, catalog = url.partition("#")
        fields.update(source="stremio", stremio_manifest=sources.mask_stremio(manifest), stremio_catalog=catalog)
    elif "themoviedb.org" in url:
        fields.update(source="tmdb", tmdb_url=url)
    else:
        fields["mdblist_url"] = url
    return fields


def list_url(source: str, fields: dict, saved_url: str = "") -> str:
    """What the list is, from the fields of the picked source: a URL or a short reference."""
    if source == "tmdb":
        return f"tmdb:{fields['tmdb_preset']}" if fields["tmdb_preset"] else fields["tmdb_url"]
    if source == "stremio":
        manifest = fields["stremio_manifest"].partition("#")[0]
        saved_manifest = saved_url.partition("#")[0]
        if MASK in manifest and sources.mask_stremio(saved_manifest) == manifest:
            manifest = saved_manifest  # the form showed the saved URL with its configuration hidden
        return f"{manifest}#{fields['stremio_catalog']}" if manifest and fields["stremio_catalog"] else manifest
    return f"mdblist:{fields['mdblist_list']}" if fields["mdblist_list"] else fields["mdblist_url"]


def list_form(
    url: str = Form(""),
    editing_id: str = Form(""),
    source: str = Form(""),
    mdblist_list: str = Form(""),
    mdblist_url: str = Form(""),
    tmdb_preset: str = Form(""),
    tmdb_url: str = Form(""),
    stremio_manifest: str = Form(""),
    stremio_catalog: str = Form(""),
    name: str = Form(""),
    library_key: str = Form(""),
    placement: str = Form("home"),
    max_items: str = Form("50"),
    audience: str = Form("all"),
    poster_source: str = Form(""),
    db: sqlite3.Connection = Depends(get_db),
) -> ListForm:
    if source in SOURCES:
        saved = get_list(db, int(editing_id)) if editing_id.isdigit() else None
        fields = {"mdblist_list": mdblist_list, "mdblist_url": mdblist_url, "tmdb_preset": tmdb_preset,
                  "tmdb_url": tmdb_url, "stremio_manifest": stremio_manifest, "stremio_catalog": stremio_catalog}
        url = list_url(source, {k: v.strip() for k, v in fields.items()}, saved.url if saved else "")
    count = int(max_items) if max_items.strip().isdigit() else 50
    return ListForm(url.strip(), name.strip(), library_key, placement if placement in PLACEMENTS else "home",
                    max(1, min(count, 500)), audience.strip() or "all", poster_source)


def _audiences(db: sqlite3.Connection) -> tuple[list[tuple[str, str]], str | None]:
    """(value, label) choices for who sees a collection, and why friends are missing if they are."""
    global _friends_cache
    choices = [("all", "Everyone"), ("owner", "Only me")]
    if _friends_cache and time.monotonic() - _friends_cache[0] < FRIENDS_TTL:
        return choices + _friends_cache[1], None
    connection = plex.load_connection(db)
    if connection is None:
        return choices, "Connect Plex to pick a friend."
    try:
        machine_id = plex.get_server(connection).machineIdentifier
        with httpx.Client() as http:
            people = sharing.friends(http, connection.token, sharing.client_id(db), machine_id)
    except sharing.SharingError as exc:
        return choices, str(exc)
    except Exception as exc:
        plex.forget_server()
        return choices, plex.describe_error(exc, connection)
    found = [(f.id, f"Only {f.name}") for f in sorted(people, key=lambda f: f.name.lower())]
    _friends_cache = (time.monotonic(), found)
    return choices + found, None


def _libraries(db: sqlite3.Connection):
    connection = plex.load_connection(db)
    if connection is None:
        return []
    try:
        return plex.visible(db, plex.cached_overview(connection)[2])
    except Exception:
        plex.forget_server()
        return []


def _form_page(request: Request, db: sqlite3.Connection, config: ListConfig, error: str | None = None):
    audiences, audience_error = _audiences(db)
    if config.audience not in dict(audiences):
        audiences.append((config.audience, f"Only {config.audience_name or 'a former friend'}"))
    return render(
        request, "collections/form.html", active="collections", page="collections/form", config=config,
        libraries=_libraries(db), placements=PLACEMENTS, presets=sources.PRESETS, error=error,
        has_tmdb_key=bool(get_setting(db, "tmdb.key")), audiences=audiences, audience_error=audience_error,
        has_mdblist_key=bool(get_setting(db, "mdblist.key")), list_sources=SOURCES, fields=source_fields(config.url),
        services=list_sources(db), default_service=get_default_source(db),
    )


def fetch_list(db: sqlite3.Connection, ref: sources.ListRef) -> sources.FetchedList:
    with httpx.Client(follow_redirects=True) as client:
        return sources.fetch(ref, client, get_setting(db, "tmdb.key"), get_setting(db, "mdblist.key"))


@router.get("/collections/mdblist")
def mdblist_picker(request: Request, selected: str = "", db: sqlite3.Connection = Depends(get_db)):
    """One menu with the user's own MDBList lists, then the popular ones."""
    groups, error = [], None
    key = get_setting(db, "mdblist.key")
    try:
        with httpx.Client(follow_redirects=True) as client:
            for which, label in (("user", "Your lists"), ("top", "Popular on MDBList")):
                groups.append((label, sources.mdblist_lists(client, key, which) if key else []))
    except sources.ListError as exc:
        error = str(exc)
    return render(request, "partials/mdblist_picker.html", groups=groups, selected=selected, error=error)


@router.post("/collections/stremio/catalogs")
def stremio_catalogs(request: Request, form: ListForm = Depends(list_form)):
    manifest, _, selected = form.url.partition("#")
    context = {"selected": selected, "catalogs": []}
    if not manifest.endswith("/manifest.json"):
        return render(request, "partials/stremio_catalogs.html",
                      error="Paste the addon's manifest URL (it ends with /manifest.json).", **context)
    try:
        with httpx.Client(follow_redirects=True) as client:
            context["catalogs"] = sources.stremio_catalogs(client, manifest)
    except sources.ListError as exc:
        context["error"] = str(exc)
    return render(request, "partials/stremio_catalogs.html", **context)


@router.get("/collections")
def collections_root():
    return RedirectResponse("/collections/lists", status_code=303)


def _panel_context(request: Request, db: sqlite3.Connection) -> dict:
    runner = request.app.state.list_runner
    default = get_default_source(db)
    services = {s.id: s.name for s in list_sources(db)}
    return {"lists": list_lists(db), "placements": PLACEMENTS, "running": runner.running, "mode": runner.mode,
            "progress": runner.progress, "results": runner.results,
            "poster_services": services, "default_service": default.name if default else None}


@router.get("/collections/lists")
def lists_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    logs = request.app.state.events.tail(80)
    return render(request, "collections/lists.html", active="collections", page="collections/lists", logs=logs,
                  **_panel_context(request, db))


@router.get("/collections/panel")
def lists_panel(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return render(request, "partials/lists_panel.html", **_panel_context(request, db))


@router.post("/collections/sync/{mode}")
def start_sync(request: Request, mode: str, list_id: str = Form(""), db: sqlite3.Connection = Depends(get_db)):
    if mode not in ("test", "live"):
        raise HTTPException(404)
    error = None
    try:
        request.app.state.list_runner.start(mode, [int(list_id)] if list_id.isdigit() else None)
    except AlreadyRunning:
        error = "A collections sync is already running."
    return render(request, "partials/lists_panel.html", error=error, **_panel_context(request, db))


@router.get("/collections/lists/new")
def new_list(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return _form_page(request, db, ListConfig(None, "", "", "", ""))


@router.get("/collections/lists/{list_id:int}")
def edit_list(request: Request, list_id: int, db: sqlite3.Connection = Depends(get_db)):
    config = get_list(db, list_id)
    if config is None:
        raise HTTPException(404)
    return _form_page(request, db, config)


@router.post("/collections/lists/preview")
def preview(request: Request, form: ListForm = Depends(list_form), db: sqlite3.Connection = Depends(get_db)):
    def fail(message: str):
        return render(request, "partials/list_preview.html", error=message)

    try:
        ref = sources.parse(form.url)
    except sources.ListError as exc:
        return fail(str(exc))
    connection = plex.load_connection(db)
    if connection is None:
        return fail("Connect Plex first, in Settings.")
    if not form.library_key:
        return fail("Pick a library.")
    try:
        fetched = fetch_list(db, ref)
    except sources.ListError as exc:
        return fail(str(exc))
    try:
        server = plex.get_server(connection)
        section = server.library.sectionByID(int(form.library_key))
        ready = ensure_index(db, server, section, background=request.app.state.db_path)
    except Exception as exc:
        plex.forget_server()
        return fail(plex.describe_error(exc, connection))
    if not ready:
        return render(request, "partials/list_preview.html", indexing=section.title, size=section.totalSize)

    result = match(db, form.library_key, section.type, fetched.items)
    ranked, owned = [], 0
    for item, rating_key in result.ranked:  # in list order, up to the last title the collection keeps
        if owned == form.max_items:
            break
        ranked.append((item, rating_key))
        owned += rating_key is not None
    missing = [item for item, rating_key in ranked if rating_key is None]
    with httpx.Client(follow_redirects=True) as client:
        with_posters = iter(sources.add_posters(missing[:MISSING_POSTERS], client, get_setting(db, "tmdb.key"))
                            + missing[MISSING_POSTERS:])
    seerr = get_setting(db, "seerr.url")
    tiles = []  # (title, rating key or None when missing, Seerr link)
    for item, rating_key in ranked:
        if rating_key is None:
            item = next(with_posters)
            tiles.append((item, None, request_url(seerr, item)))
        else:
            tiles.append((item, rating_key, None))
    return render(
        request, "partials/list_preview.html", name=form.name or fetched.name, ref=ref, result=result,
        tiles=tiles, kept=owned, missing_shown=len(missing), library=section.title, has_seerr=bool(seerr),
    )


def request_url(seerr: str | None, item: sources.ListItem) -> str | None:
    """The title's page in Seerr (Overseerr and Jellyseerr alike), or a search when its TMDB id is unknown."""
    if not seerr:
        return None
    if item.tmdb_id:
        return f"{seerr}/{'movie' if item.kind == 'movie' else 'tv'}/{item.tmdb_id}"
    return f"{seerr}/search?query={quote(item.title)}"


def _save(request: Request, db: sqlite3.Connection, list_id: int | None, form: ListForm):
    config = ListConfig(list_id, form.name, form.url, form.library_key, "", form.placement, form.max_items,
                        audience=form.audience)
    services = {s.id for s in list_sources(db)}
    if form.poster_source == "default" or (form.poster_source.isdigit() and int(form.poster_source) in services):
        config.posters = True
        config.poster_source_id = int(form.poster_source) if form.poster_source.isdigit() else None
    labels = dict(_audiences(db)[0])
    if form.audience not in labels:
        saved = get_list(db, list_id) if list_id else None
        if saved is None or saved.audience != form.audience:
            return _form_page(request, db, config, "Pick who sees this collection.")
        config.audience_name = saved.audience_name
    elif form.audience not in ("all", "owner"):
        config.audience_name = labels[form.audience].removeprefix("Only ")
    try:
        ref = sources.parse(form.url)
    except sources.ListError as exc:
        return _form_page(request, db, config, str(exc))
    library = next((lib for lib in _libraries(db) if lib.key == form.library_key), None)
    if library is None:
        return _form_page(request, db, config, "Pick a library.")
    config.library_title = library.title
    if not config.name:
        try:
            config.name = fetch_list(db, ref).name
        except sources.ListError:
            config.name = ref.name
    if list_id is not None:
        saved = get_list(db, list_id)
        if saved is None:
            raise HTTPException(404)
        config.enabled = saved.enabled
    save_list(db, config)
    return RedirectResponse("/collections/lists", status_code=303)


@router.post("/collections/lists")
def create_list(request: Request, form: ListForm = Depends(list_form), db: sqlite3.Connection = Depends(get_db)):
    return _save(request, db, None, form)


@router.post("/collections/lists/{list_id:int}")
def update_list(
    request: Request, list_id: int, form: ListForm = Depends(list_form), db: sqlite3.Connection = Depends(get_db)
):
    return _save(request, db, list_id, form)


@router.post("/collections/lists/{list_id:int}/delete")
def remove_list(request: Request, list_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Deletes the list and its Plex collection: it was made by this app."""
    config = get_list(db, list_id)
    if config is None:
        raise HTTPException(404)
    connection = plex.load_connection(db)
    if config.collection_key and connection is not None:
        try:
            if delete_collection(plex.get_server(connection), config):
                request.app.state.events.info(f"{config.name}: collection deleted from Plex")
        except Exception as exc:
            plex.forget_server()
            request.app.state.events.add("error", f"{config.name}: {plex.describe_error(exc, connection)}")
    delete_list(db, list_id)
    return RedirectResponse("/collections/lists", status_code=303)


@router.get("/collections/order")
def order_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    return render(request, "collections/order.html", active="collections", page="collections/order",
                  libraries=_libraries(db))


def _hubs_card(request: Request, db: sqlite3.Connection, library_key: str, move=None):
    connection = plex.load_connection(db)
    if connection is None:
        return render(request, "partials/hub_order.html", error="Plex is not configured.", library_key=library_key)
    try:
        section = plex.get_server(connection).library.sectionByID(int(library_key))
        hubs = section.managedHubs()
        if move:
            hubs = move(hubs)
    except Exception as exc:
        plex.forget_server()
        return render(request, "partials/hub_order.html", error=plex.describe_error(exc, connection),
                      library_key=library_key)
    ours = {f"custom.collection.{library_key}.{c.collection_key}" for c in list_lists(db) if c.collection_key}
    return render(request, "partials/hub_order.html", hubs=hubs, ours=ours, library_key=library_key)


@router.get("/collections/order/{library_key}")
def library_hubs(request: Request, library_key: str, db: sqlite3.Connection = Depends(get_db)):
    return _hubs_card(request, db, library_key)


@router.post("/collections/order/{library_key}/move")
def move_hub(
    request: Request,
    library_key: str,
    identifier: str = Form(...),
    direction: str = Form(...),
    db: sqlite3.Connection = Depends(get_db),
):
    def move(hubs):
        index = next((i for i, hub in enumerate(hubs) if hub.identifier == identifier), None)
        if index is None:
            return hubs
        if direction == "up" and index > 0:
            hubs[index].move(after=hubs[index - 2] if index > 1 else None)
            hubs.insert(index - 1, hubs.pop(index))
        elif direction == "down" and index < len(hubs) - 1:
            hubs[index].move(after=hubs[index + 1])
            hubs.insert(index + 1, hubs.pop(index))
        return hubs

    return _hubs_card(request, db, library_key, move)


@dataclass
class PlexCollection:
    key: str
    title: str
    count: int
    smart: bool
    origin: str | None
    list: ListConfig | None


@router.get("/collections/plex")
def plex_collections_page(request: Request, db: sqlite3.Connection = Depends(get_db)):
    libraries = [lib for lib in _libraries(db) if lib.type in ("movie", "show")]
    return render(request, "collections/plex.html", active="collections", page="collections/plex",
                  libraries=libraries)


def _collections_card(request: Request, db: sqlite3.Connection, library_key: str, notice=None, error=None):
    context = {"library_key": library_key, "notice": notice, "error": error, "rows": None}
    connection = plex.load_connection(db)
    if connection is None:
        context["error"] = "Plex is not configured."
        return render(request, "partials/plex_collections.html", **context)
    try:
        found = plex.get_server(connection).library.sectionByID(int(library_key)).collections()
    except Exception as exc:
        plex.forget_server()
        context["error"] = plex.describe_error(exc, connection)
        return render(request, "partials/plex_collections.html", **context)
    linked = {c.collection_key: c for c in list_lists(db) if c.collection_key}
    context["rows"] = [
        PlexCollection(str(c.ratingKey), c.title, int(c.childCount or 0), bool(c.smart),
                       made_by(c, str(c.ratingKey) in linked), linked.get(str(c.ratingKey)))
        for c in found
    ]
    return render(request, "partials/plex_collections.html", **context)


@router.get("/collections/plex/{library_key}")
def library_collections(request: Request, library_key: str, db: sqlite3.Connection = Depends(get_db)):
    return _collections_card(request, db, library_key)


@router.post("/collections/plex/{library_key}/delete")
def delete_plex_collection(
    request: Request, library_key: str, rating_key: str = Form(...), db: sqlite3.Connection = Depends(get_db)
):
    """Deletes a collection this app doesn't manage (made by hand or by another tool). Its titles stay."""
    owner = next((c for c in list_lists(db) if c.collection_key == rating_key), None)
    if owner is not None:
        return _collections_card(request, db, library_key,
                                 error=f"It belongs to the list {owner.name}: delete the list instead.")
    connection = plex.load_connection(db)
    if connection is None or not rating_key.isdigit():
        return _collections_card(request, db, library_key)
    try:
        collection = plex.get_server(connection).fetchItem(int(rating_key))
        if getattr(collection, "TYPE", None) != "collection" or str(collection.librarySectionID) != library_key:
            raise NotFound(rating_key)
        title = collection.title
        collection.delete()
    except NotFound:
        return _collections_card(request, db, library_key, notice="That collection is already gone.")
    except Exception as exc:
        plex.forget_server()
        return _collections_card(request, db, library_key, error=plex.describe_error(exc, connection))
    request.app.state.events.info(f"Collection {title} deleted from Plex")
    return _collections_card(request, db, library_key, notice=f"{title} deleted. Its titles are still in Plex.")


LISTS_SCHEDULE_CARD = {"schedule_url": "/collections/schedule", "intervals": INTERVALS,
                       "schedule_what": "every list is synced to Plex."}


@router.get("/collections/schedule")
def lists_schedule(request: Request, db: sqlite3.Connection = Depends(get_db)):
    schedule = load_schedule(db, LISTS_SCHEDULE)
    return render(request, "partials/schedule_card.html", schedule=schedule, **LISTS_SCHEDULE_CARD)


@router.post("/collections/schedule")
def update_lists_schedule(
    request: Request,
    enabled: str = Form(""),
    every_hours: str = Form(str(DEFAULT_INTERVAL)),
    db: sqlite3.Connection = Depends(get_db),
):
    hours = int(every_hours) if every_hours.isdigit() else DEFAULT_INTERVAL
    schedule = save_schedule(db, bool(enabled), hours, prefix=LISTS_SCHEDULE)
    return render(request, "partials/schedule_card.html", schedule=schedule, saved=True, **LISTS_SCHEDULE_CARD)
