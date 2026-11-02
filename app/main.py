import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.branding import APP_NAME, APP_SLUG, APP_VERSION, REPO_URL
from app.config import Env, load_env
from app.db import connection, migrate
from app.settings_store import seed_setting
from app.lists.runner import ListRunner
from app.sync.events import EventLog
from app.sync.runner import SyncRunner, mark_interrupted_runs
from app.sync.scheduler import LISTS_SCHEDULE, Scheduler
from app.updates import UpdateCheck
from app.web import collections, dashboard, plex_images, scope, settings, sources, sync, titles
from app.web.assets import asset
from app.web.formatting import ago, duration, until
from app.web.icons import icon

BASE_DIR = Path(__file__).parent

log = logging.getLogger(__name__)


def _seed_from_env(env: Env, db_path: Path) -> None:
    with connection(db_path) as conn:
        if env.plex_url:
            seed_setting(conn, "plex.url", env.plex_url.rstrip("/"))
        if env.plex_token:
            seed_setting(conn, "plex.token", env.plex_token)


def create_app(env: Env | None = None) -> FastAPI:
    env = env or load_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        env.data_dir.mkdir(parents=True, exist_ok=True)
        version = migrate(app.state.db_path)
        log.info("Database ready at %s (schema v%s)", app.state.db_path, version)
        _seed_from_env(env, app.state.db_path)
        with connection(app.state.db_path) as conn:
            mark_interrupted_runs(conn)
        app.state.events = EventLog()
        app.state.runner = SyncRunner(app.state.db_path, app.state.events)
        app.state.list_runner = ListRunner(app.state.db_path, app.state.events, app.state.runner)
        app.state.scheduler = Scheduler(app.state.db_path, app.state.runner, app.state.events)
        app.state.scheduler.start()
        app.state.list_scheduler = Scheduler(app.state.db_path, app.state.list_runner, app.state.events,
                                             prefix=LISTS_SCHEDULE, label="collections sync")
        app.state.list_scheduler.start()
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            app.state.http = http
            yield
        app.state.scheduler.stop()
        app.state.list_scheduler.stop()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.env = env
    app.state.db_path = env.data_dir / f"{APP_SLUG}.db"

    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.updates = UpdateCheck(env.update_check)
    templates.env.globals.update(app_name=APP_NAME, app_version=APP_VERSION, repo_url=REPO_URL, icon=icon, asset=asset,
                                 active=None, newer_version=app.state.updates.newer)
    templates.env.filters.update(ago=ago, duration=duration, until=until)
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(dashboard.router)
    app.include_router(settings.router)
    app.include_router(sources.router)
    app.include_router(scope.router)
    app.include_router(sync.router)
    app.include_router(titles.router)
    app.include_router(collections.router)
    app.include_router(plex_images.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}

    return app


app = create_app()
