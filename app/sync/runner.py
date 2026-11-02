"""Runs a sync in a background thread, one at a time.

A test sync only reports what would change. A live sync downloads each new
poster and uploads it to Plex, then remembers its fingerprint so the next
sync skips it.
"""

import logging
import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from app import db
from app.plex import client as plex
from app.posters import fetch
from app.posters.sources import get_default_source, list_sources
from app.scope import list_scope
from app.secrets import mask
from app.sync.engine import Outcome, Target, collect_targets, evaluate, remember, upload
from app.sync.events import EventLog

log = logging.getLogger(__name__)

KEEP_RUNS = 30
WORKERS = 4
COUNTERS = {"apply": "applied", "unchanged": "unchanged", "skipped": "skipped", "error": "errors"}


class AlreadyRunning(Exception):
    pass


@dataclass
class Result:
    target: Target
    outcome: Outcome
    level: str = "info"
    message: str = ""


def mark_interrupted_runs(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE runs SET status = 'failed', error = 'Interrupted (the app stopped)', finished_at = CURRENT_TIMESTAMP"
        " WHERE status = 'running'"
    )


class SyncRunner:
    def __init__(self, db_path: Path, events: EventLog, workers: int = WORKERS):
        self.db_path = db_path
        self.events = events
        self.workers = workers
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self.run_id: int | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self, mode: str = "test", max_items: int | None = None, scheduled: bool = False
    ) -> int:
        with self._lock:
            if self.running:
                raise AlreadyRunning()
            with db.connection(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT ?)", (KEEP_RUNS - 1,)
                )
                cursor = conn.execute(
                    "INSERT INTO runs (mode, max_items, fetch_images, scheduled) VALUES (?, ?, ?, ?)",
                    (mode, max_items, 0, int(scheduled)),
                )
                self.run_id = cursor.lastrowid
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run, args=(self.run_id, mode, max_items), name="sync", daemon=True
            )
            self._thread.start()
            return self.run_id

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, run_id: int, mode: str, max_items: int | None) -> None:
        name = "Test sync" if mode == "test" else "Sync"
        conn = db.open_db(self.db_path)
        try:
            status, error = self._process(conn, run_id, mode, max_items)
        except Exception as exc:
            log.exception("Sync failed")
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        if error:
            self.events.add("error", f"{name} failed: {error}")
        conn.execute(
            "UPDATE runs SET status = ?, error = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, error, run_id),
        )
        conn.commit()
        conn.close()

    def _process(self, conn: sqlite3.Connection, run_id: int, mode: str, max_items: int | None):
        live = mode == "live"
        connection = plex.load_connection(conn)
        if connection is None:
            return "failed", "Plex is not configured."
        entries = list_scope(conn)
        if not entries:
            return "failed", "Nothing is picked in Posters → Libraries."
        sources = {s.id: s for s in list_sources(conn)}
        default = get_default_source(conn)
        state = dict(conn.execute("SELECT rating_key, fingerprint FROM poster_state").fetchall())

        limit = f"first {max_items} titles" if max_items else "all titles"
        if live:
            self.events.info(f"Sync started ({limit})")
        else:
            self.events.info(f"Test sync started ({limit}, nothing is sent to Plex)")
        try:
            server = plex.connect(connection)
        except Exception as exc:
            return "failed", plex.describe_error(exc, connection)

        counts = dict.fromkeys(COUNTERS.values(), 0)
        done_count = 0
        positions: dict[Future, int] = {}

        def finish(future: Future) -> None:
            nonlocal done_count
            result = future.result()
            done_count += 1
            counts[COUNTERS[result.outcome.action]] += 1
            if result.message:
                self.events.add(result.level, result.message)
            self._record(conn, run_id, positions.pop(future), result.target, result.outcome)
            if live and result.outcome.action == "apply":
                remember(conn, str(result.target.item.ratingKey), result.outcome.fingerprint)
            conn.execute(
                "UPDATE runs SET total = ?, applied = ?, unchanged = ?, skipped = ?, errors = ? WHERE id = ?",
                (done_count, counts["applied"], counts["unchanged"], counts["skipped"], counts["errors"], run_id),
            )
            conn.commit()

        submitted = 0
        pending: set[Future] = set()
        with ThreadPoolExecutor(self.workers, thread_name_prefix="sync-item") as pool:
            for target in collect_targets(server, entries, sources, default, lambda m: self.events.add("warn", m)):
                if self._cancel.is_set() or (max_items and submitted >= max_items):
                    break
                previous = state.get(str(target.item.ratingKey))
                future = pool.submit(self._handle, target, previous, live)
                submitted += 1
                positions[future] = submitted
                pending.add(future)
                if len(pending) >= self.workers * 2:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        finish(future)
            if self._cancel.is_set():
                for future in pending:
                    future.cancel()
                pending = {f for f in pending if not f.cancelled()}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    finish(future)

        if self._cancel.is_set():
            self.events.add("warn", f"{'Sync' if live else 'Test sync'} cancelled")
            return "cancelled", None
        if live:
            summary = f"Sync done: {done_count} titles, {counts['applied']} posters sent to Plex"
        else:
            summary = f"Test sync done: {done_count} titles, {counts['applied']} would get a new poster"
        self.events.add("ok", f"{summary}, {counts['skipped']} skipped, {counts['errors']} errors")
        return "done", None

    def _handle(self, target: Target, previous: str | None, live: bool) -> Result:
        """Runs in a worker thread: everything that talks to Plex or the poster service."""
        name = target.item.title
        source = target.source
        try:
            outcome = evaluate(target, previous)
        except Exception as exc:
            reason = mask(f"{type(exc).__name__}: {exc}", source.secrets)
            return Result(target, Outcome("error", reason=reason), "error", f"{name}: {reason}")

        if outcome.action == "skipped":
            return Result(target, outcome, "warn", f"{name}: skipped, {outcome.reason}")
        if outcome.action == "unchanged":
            return Result(target, outcome)

        quality = ",".join(outcome.info.quality) or "no quality"
        why = f", {outcome.reason}" if outcome.reason else ""
        if not live:
            return Result(target, outcome, "info", f"{name}: would get a poster from {source.name} ({quality}){why}")

        image = fetch.fetch_poster(outcome.url, source.headers, source.timeout, source.secrets)
        if not image.ok:
            outcome.action, outcome.reason = "error", image.error
            return Result(target, outcome, "error", f"{name}: {image.error}")
        try:
            upload(target.item, image.content)
        except Exception as exc:
            reason = mask(f"Upload to Plex failed: {type(exc).__name__}: {exc}", source.secrets)
            outcome.action, outcome.reason = "error", reason
            return Result(target, outcome, "error", f"{name}: {reason}")
        return Result(target, outcome, "ok", f"{name}: poster updated from {source.name} ({quality}){why}")

    def _record(self, conn: sqlite3.Connection, run_id: int, position: int, target: Target, outcome: Outcome) -> None:
        item = target.item
        conn.execute(
            "INSERT OR REPLACE INTO run_items (run_id, position, rating_key, title, year, type, library, thumb,"
            " source_name, quality, action, reason, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id, position, str(item.ratingKey), item.title, getattr(item, "year", None), item.TYPE,
                target.library, getattr(item, "thumb", None), target.source.name,
                ",".join(outcome.info.quality) if outcome.info else "", outcome.action, outcome.reason,
                outcome.masked_url,
            ),
        )
