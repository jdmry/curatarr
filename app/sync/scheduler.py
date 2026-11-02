"""Starts a sync to Plex every few hours: posters, or collections."""

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import db
from app.settings_store import get_setting, set_setting
from app.sync.events import EventLog
from app.sync.runner import AlreadyRunning

log = logging.getLogger(__name__)

INTERVALS = (1, 3, 6, 12, 24)
DEFAULT_INTERVAL = 6
TICK = 30
LISTS_SCHEDULE = "lists_schedule"


@dataclass
class Schedule:
    enabled: bool = False
    every_hours: int = DEFAULT_INTERVAL
    next_at: datetime | None = None


def load_schedule(conn: sqlite3.Connection, prefix: str = "schedule") -> Schedule:
    next_at = get_setting(conn, f"{prefix}.next_at")
    return Schedule(
        enabled=bool(get_setting(conn, f"{prefix}.enabled", False)),
        every_hours=int(get_setting(conn, f"{prefix}.every_hours", DEFAULT_INTERVAL)),
        next_at=datetime.fromisoformat(next_at) if next_at else None,
    )


def save_schedule(
    conn: sqlite3.Connection, enabled: bool, every_hours: int, now: datetime | None = None, prefix: str = "schedule"
) -> Schedule:
    """Turning it on (or changing the interval) counts from now: no surprise sync right away."""
    if every_hours not in INTERVALS:
        every_hours = DEFAULT_INTERVAL
    now = now or datetime.now(UTC)
    next_at = now + timedelta(hours=every_hours) if enabled else None
    set_setting(conn, f"{prefix}.enabled", enabled)
    set_setting(conn, f"{prefix}.every_hours", every_hours)
    set_setting(conn, f"{prefix}.next_at", next_at.isoformat() if next_at else None)
    return Schedule(enabled, every_hours, next_at)


class Scheduler:
    """`prefix` names its settings ("schedule" for posters, "lists_schedule" for collections)."""

    def __init__(self, db_path: Path, runner, events: EventLog, tick: float = TICK, prefix: str = "schedule",
                 label: str = "sync"):
        self.db_path = db_path
        self.runner = runner
        self.events = events
        self.tick = tick
        self.prefix = prefix
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)

    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                self.check()
            except Exception:
                log.exception("Scheduler check failed")

    def check(self, now: datetime | None = None) -> bool:
        """Start the sync if it is due. A sync already running delays it to the next tick."""
        now = now or datetime.now(UTC)
        with db.connection(self.db_path) as conn:
            schedule = load_schedule(conn, self.prefix)
            if not schedule.enabled or schedule.next_at is None or schedule.next_at > now:
                return False
            try:
                self.runner.start("live", scheduled=True)
            except AlreadyRunning:
                return False
            set_setting(conn, f"{self.prefix}.next_at", (now + timedelta(hours=schedule.every_hours)).isoformat())
        self.events.info(f"Scheduled {self.label} (every {schedule.every_hours} h)")
        return True
