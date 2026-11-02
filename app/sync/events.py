"""In-memory activity log, streamed to the dashboard."""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("curatarr.sync")


@dataclass(frozen=True)
class LogLine:
    id: int
    time: datetime
    level: str  # info, ok, warn, error
    message: str


class EventLog:
    def __init__(self, size: int = 500):
        self._lines: deque[LogLine] = deque(maxlen=size)
        self._next_id = 1
        self._lock = threading.Lock()

    def add(self, level: str, message: str) -> None:
        with self._lock:
            self._lines.append(LogLine(self._next_id, datetime.now(), level, message))
            self._next_id += 1
        log.log(logging.WARNING if level in ("warn", "error") else logging.INFO, message)

    def info(self, message: str) -> None:
        self.add("info", message)

    def since(self, last_id: int) -> list[LogLine]:
        with self._lock:
            return [line for line in self._lines if line.id > last_id]

    def tail(self, count: int) -> list[LogLine]:
        with self._lock:
            return list(self._lines)[-count:]
