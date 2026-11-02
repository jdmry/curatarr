"""Settings read from environment variables.

Everything user-facing is configured in the web UI and stored in the database.
Environment variables only cover what is needed before the UI exists (where
to store data, which port to listen on) and optional initial values.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Env:
    data_dir: Path
    port: int
    plex_url: str | None
    plex_token: str | None
    log_level: str
    update_check: bool = True
    admin_username: str | None = None  # make the admin account at the first start
    admin_password: str | None = None


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_env() -> Env:
    return Env(
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        port=int(os.environ.get("PORT", "8080")),
        plex_url=_optional("PLEX_URL"),
        plex_token=_optional("PLEX_TOKEN"),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        admin_username=_optional("ADMIN_USERNAME"),
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
        update_check=os.environ.get("UPDATE_CHECK", "true").strip().lower() not in ("0", "false", "no", "off"),
    )
