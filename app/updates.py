"""Is a newer release out? GitHub is asked at most once a day, in the background."""

import logging
import threading
import time

import httpx

from app.branding import APP_VERSION, REPO

log = logging.getLogger(__name__)

API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 86400


def parse(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.strip().lstrip("v").split("."))
    except ValueError:
        return None


class UpdateCheck:
    def __init__(self, enabled: bool = True, current: str = APP_VERSION):
        self.enabled = enabled
        self.current = current
        self.latest: str | None = None
        self._checked = 0.0
        self._lock = threading.Lock()

    def newer(self) -> str | None:
        """The latest release when it is newer than this one. Never waits for GitHub."""
        if self.enabled and time.time() - self._checked > CHECK_EVERY and self._lock.acquire(blocking=False):
            self._checked = time.time()
            threading.Thread(target=self._check, name="update-check", daemon=True).start()
        current, latest = parse(self.current), parse(self.latest or "")
        return self.latest if current and latest and latest > current else None

    def _check(self) -> None:
        try:
            response = httpx.get(API, timeout=10, headers={"Accept": "application/vnd.github+json"})
            if response.status_code == 200:
                self.latest = (response.json().get("tag_name") or "").lstrip("v") or None
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Update check failed: %s", exc)
        finally:
            self._lock.release()
