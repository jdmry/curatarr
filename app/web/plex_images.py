"""Plex images for the browser, fetched server-side.

The browser never sees the Plex token: it asks this route, which fetches the
image from Plex (resized by Plex's own transcoder) and passes it through.
Nothing is stored on disk; the browser caches the response.
"""

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app import db
from app.plex.client import load_connection

router = APIRouter()

MAX_SIZE = 1000


@router.get("/plex/image")
async def plex_image(request: Request, path: str, w: int = 300, h: int = 450):
    if not path.startswith("/library/") or ".." in path:
        raise HTTPException(400, "Only Plex library images can be fetched.")
    with db.connection(request.app.state.db_path) as conn:
        connection = load_connection(conn)
    if connection is None:
        raise HTTPException(404, "Plex is not configured.")

    params = {
        "url": path,
        "width": max(1, min(w, MAX_SIZE)),
        "height": max(1, min(h, MAX_SIZE)),
        "minSize": 1,
        "upscale": 1,
    }
    http: httpx.AsyncClient = request.app.state.http
    try:
        upstream = await http.get(
            f"{connection.url}/photo/:/transcode",
            params=params,
            headers={"X-Plex-Token": connection.token, "Accept": "image/*"},
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach Plex.") from None
    if upstream.status_code != 200:
        raise HTTPException(502, f"Plex answered {upstream.status_code}.")
    return Response(
        upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "private, max-age=86400"},
    )
