import sqlite3
from collections.abc import Iterator

from fastapi import Request

from app.db import connection
from app.web.banners import banners_for


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with connection(request.app.state.db_path) as conn:
        yield conn


def render(request: Request, template: str, **context):
    """Render a template. Full pages pass `page` (e.g. "posters/sync") to get setup banners."""
    if "page" in context:
        context["banners"] = banners_for(request.app.state.db_path, context["page"])
    return request.app.state.templates.TemplateResponse(request, template, context)
