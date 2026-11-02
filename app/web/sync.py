import asyncio
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from markupsafe import escape

from app.scope import list_scope
from app.sync.runner import AlreadyRunning
from app.web.deps import get_db, render

router = APIRouter()

PAGE = 100


def last_run(db: sqlite3.Connection):
    return db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()


@router.get("/posters")
def posters_root():
    return RedirectResponse("/posters/sync", status_code=303)


@router.get("/posters/sync")
def posters_sync(request: Request):
    logs = request.app.state.events.tail(80)
    return render(request, "posters/sync.html", active="posters", page="posters/sync", logs=logs)


@router.get("/posters/history")
def posters_history(request: Request, db: sqlite3.Connection = Depends(get_db)):
    runs = db.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return render(request, "posters/history.html", active="posters", page="posters/history", runs=runs)


@router.get("/sync/card")
def sync_card(request: Request, db: sqlite3.Connection = Depends(get_db)):
    runner = request.app.state.runner
    return render(request, "partials/sync_card.html", run=last_run(db), running=runner.running,
                  has_scope=bool(list_scope(db)))


def _start(request: Request, db: sqlite3.Connection, mode: str, max_items: str):
    runner = request.app.state.runner
    limit = int(max_items) if max_items.strip().isdigit() and int(max_items) > 0 else None
    error = None
    try:
        runner.start(mode, limit)
    except AlreadyRunning:
        error = "A sync is already running."
    return render(request, "partials/sync_card.html", run=last_run(db), running=runner.running, error=error,
                  has_scope=bool(list_scope(db)))


@router.post("/sync/test")
def start_test(request: Request, max_items: str = Form("20"), db: sqlite3.Connection = Depends(get_db)):
    return _start(request, db, "test", max_items)


@router.post("/sync/live")
def start_live(request: Request, max_items: str = Form("20"), db: sqlite3.Connection = Depends(get_db)):
    return _start(request, db, "live", max_items)


@router.post("/sync/cancel")
def cancel(request: Request, db: sqlite3.Connection = Depends(get_db)):
    request.app.state.runner.cancel()
    return render(request, "partials/sync_card.html", run=last_run(db), running=request.app.state.runner.running)


def _log_html(line) -> str:
    return (
        f'<li class="log-{line.level}"><time>{line.time:%H:%M:%S}</time>'
        f"<span>{escape(line.message)}</span></li>"
    )


HEARTBEAT = 20


@router.get("/events/logs")
async def log_stream(request: Request, after: int = 0):
    """`after` is the last line already rendered in the page; Last-Event-ID wins on reconnect."""
    events = request.app.state.events
    last_id = int(request.headers.get("Last-Event-ID", 0) or after)

    async def stream():
        nonlocal last_id
        quiet = 0.0
        while not await request.is_disconnected():
            for line in events.since(last_id):
                last_id, quiet = line.id, 0.0
                yield f"id: {line.id}\nevent: log\ndata: {_log_html(line)}\n\n"
            if quiet >= HEARTBEAT:
                quiet = 0.0
                yield ": ping\n\n"  # reverse proxies close streams that stay silent (nginx: 60 s)
            await asyncio.sleep(0.5)
            quiet += 0.5

    # X-Accel-Buffering: nginx (CapRover) would otherwise hold events back.
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/posters/history/{run_id:int}")
def run_page(
    request: Request, run_id: int, action: str = "", page: int = 1, db: sqlite3.Connection = Depends(get_db)
):
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise HTTPException(404)
    where, params = "run_id = ?", [run_id]
    if action:
        where += " AND action = ?"
        params.append(action)
    total = db.execute(f"SELECT COUNT(*) FROM run_items WHERE {where}", params).fetchone()[0]
    page = max(1, page)
    items = db.execute(
        f"SELECT * FROM run_items WHERE {where} ORDER BY position LIMIT ? OFFSET ?", [*params, PAGE, (page - 1) * PAGE]
    ).fetchall()
    return render(
        request, "posters/run.html", active="posters", page="posters/run", run=run, items=items, action=action, page_no=page,
        pages=max(1, -(-total // PAGE)), total=total,
    )
