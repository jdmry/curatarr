"""Syncs lists to Plex collections in a background thread, one sync at a time."""

import logging
import sqlite3
import threading
from pathlib import Path

import httpx

from app import db
from app.lists import collections, sources
from app.lists.matching import match
from app.lists.store import ListConfig, list_lists
from app.plex import client as plex
from app.plex import sharing
from app.plex.guid_index import ensure_index, forget_index
from app.settings_store import get_setting, set_setting
from app.sync.events import EventLog
from app.sync.runner import AlreadyRunning

log = logging.getLogger(__name__)


class ListRunner:
    def __init__(self, db_path: Path, events: EventLog):
        self.db_path = db_path
        self.events = events
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.mode: str | None = None
        self.results: dict[int, str] = {}  # list id -> what happened (or would), from the last sync

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, mode: str = "test", list_ids: list[int] | None = None, scheduled: bool = False) -> None:
        with self._lock:
            if self.running:
                raise AlreadyRunning()
            self.mode = mode
            self.results = {}
            self._thread = threading.Thread(target=self._run, args=(mode, list_ids), name="lists", daemon=True)
            self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, mode: str, list_ids: list[int] | None) -> None:
        name = "Collections test" if mode == "test" else "Collections sync"
        try:
            with db.connection(self.db_path) as conn:
                self._process(conn, mode, list_ids, name)
        except Exception as exc:
            log.exception("Collections sync failed")
            self.events.add("error", f"{name} failed: {type(exc).__name__}: {exc}")

    def _process(self, conn: sqlite3.Connection, mode: str, list_ids: list[int] | None, name: str) -> None:
        live = mode == "live"
        connection = plex.load_connection(conn)
        if connection is None:
            self.events.add("error", f"{name}: Plex is not configured.")
            return
        configs = [c for c in list_lists(conn) if (c.id in list_ids if list_ids else c.enabled)]
        if not configs:
            self.events.add("warn", f"{name}: no list to sync.")
            return
        self.events.info(f"{name} started ({len(configs)} list{'s' if len(configs) > 1 else ''}"
                         f"{'' if live else ', nothing is sent to Plex'})")
        try:
            server = plex.connect(connection)
        except Exception as exc:
            self.events.add("error", f"{name}: {plex.describe_error(exc, connection)}")
            return
        keys = {"tmdb_key": get_setting(conn, "tmdb.key"), "mdblist_key": get_setting(conn, "mdblist.key")}
        with httpx.Client(follow_redirects=True) as http:
            for config in configs:
                try:
                    summary = self._sync_list(conn, server, http, keys, config, live)
                except sources.ListError as exc:
                    summary = None
                    self._record(conn, config, error=str(exc))
                    self.events.add("error", f"{config.name}: {exc}")
                except Exception as exc:
                    summary = None
                    error = plex.describe_error(exc, connection)
                    self._record(conn, config, error=error)
                    self.events.add("error", f"{config.name}: {error}")
                    log.exception("List %s failed", config.name)
                if summary:
                    self.results[config.id] = summary
                conn.commit()
            self._sync_sharing(conn, server, http, connection.token, live)
        self.events.add("ok", f"{name} done")

    def _sync_sharing(self, conn: sqlite3.Connection, server, http: httpx.Client, token: str, live: bool) -> None:
        """Hide each private collection from the friends it isn't for."""
        private = [c for c in list_lists(conn) if c.private]
        if not private and not get_setting(conn, "sharing.labels"):
            return  # nothing private now or before: no need to ask plex.tv
        try:
            people = sharing.friends(http, token, sharing.client_id(conn), server.machineIdentifier)
        except sharing.SharingError as exc:
            self.events.add("error", f"Friends' restrictions: {exc}")
            return
        hidden = {f.id: {sharing.private_label(c.id) for c in private if c.audience != f.id} for f in people}
        failed = False
        for friend in people:
            filters = sharing.wanted_filters(friend, hidden)
            if not sharing.changed(friend, filters):
                continue
            count = len(hidden[friend.id])
            what = f"{count} private collection{'s' if count != 1 else ''} hidden"
            if not live:
                self.events.info(f"{friend.name}, test: restrictions would change ({what})")
                continue
            try:
                sharing.update(http, token, sharing.client_id(conn), friend, filters)
            except sharing.SharingError as exc:
                failed = True
                self.events.add("error", f"{friend.name}: {exc}")
            else:
                self.events.add("ok", f"{friend.name}: restrictions updated ({what})")
        if live and not failed:
            set_setting(conn, "sharing.labels", bool(private))

    def _sync_list(self, conn, server, http, keys: dict, config: ListConfig, live: bool) -> str:
        fetched = sources.fetch(sources.parse(config.url), http, **keys)
        section = server.library.sectionByID(int(config.library_key))
        ensure_index(conn, server, section)
        result = match(conn, config.library_key, section.type, fetched.items)
        keys = [key for _, key in result.owned][:config.max_items]
        wanted = collections.fetch_items(server, keys)
        if len(wanted) < len(keys):
            forget_index(conn, config.library_key)  # titles gone from Plex: rebuild the index next time

        collection = collections.find_collection(server, config)
        steps = collections.plan(collection, config, [str(item.ratingKey) for item in wanted])
        summary = steps.describe(len(wanted))
        if live:
            collection = collections.apply(server, section, collection, config, wanted, steps)
            key = str(collection.ratingKey) if collection is not None else None
            self._record(conn, config, total=result.total, matched=len(wanted), collection_key=key)
            self.events.add("ok" if steps.changed else "info",
                            f"{config.name}: {summary} ({len(wanted)} of {result.total} titles)")
        else:
            self.events.info(f"{config.name}, test: {summary} ({len(wanted)} of {result.total} titles)")
        return summary

    @staticmethod
    def _record(conn, config: ListConfig, total=None, matched=None, collection_key=None, error=None) -> None:
        if error:
            conn.execute("UPDATE lists SET last_error = ?, synced_at = CURRENT_TIMESTAMP WHERE id = ?", (error, config.id))
            return
        conn.execute(
            "UPDATE lists SET last_error = NULL, last_total = ?, last_matched = ?, collection_key = ?,"
            " synced_at = CURRENT_TIMESTAMP WHERE id = ?",
            (total, matched, collection_key, config.id),
        )
