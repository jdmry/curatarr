"""Who sees a collection: friends' sharing restrictions on plex.tv.

Plex has no per-user collections. A collection meant for some people only gets
a label, and every other friend gets that label in the "exclude labels"
restriction of their share. The owner always sees everything.

Only this app's labels are added or removed: other restrictions (content
ratings, labels set by hand or by other tools) are sent back unchanged.
"""

import sqlite3
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import unquote

import httpx

from app.branding import APP_NAME, APP_SLUG
from app.secrets import mask
from app.settings_store import get_setting, set_setting

API = "https://clients.plex.tv/api/v2"
TIMEOUT = 30
PRIVATE_PREFIX = f"{APP_SLUG}-private-"
FILTERS = ("filterMovies", "filterTelevision")


class SharingError(Exception):
    pass


@dataclass
class Friend:
    id: str
    username: str
    name: str
    settings: dict[str, str]  # sharingSettings attributes as plex.tv sends them


def private_label(list_id: int) -> str:
    return f"{PRIVATE_PREFIX}{list_id}"


def client_id(conn: sqlite3.Connection) -> str:
    """plex.tv wants a stable id for each app install."""
    value = get_setting(conn, "plex.client_id")
    if not value:
        value = str(uuid.uuid4())
        set_setting(conn, "plex.client_id", value)
    return value


def _headers(token: str, client: str, accept: str) -> dict:
    return {"X-Plex-Token": token, "X-Plex-Client-Identifier": client, "X-Plex-Product": APP_NAME, "Accept": accept}


def friends(http: httpx.Client, token: str, client: str, machine_id: str) -> list[Friend]:
    """Everyone this server is shared with."""
    try:
        response = http.get(f"{API}/shared_servers/owned/accepted", headers=_headers(token, client, "application/xml"),
                            timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise SharingError(f"Could not reach plex.tv: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise SharingError(f"plex.tv answered HTTP {response.status_code} when listing friends.")
    result = []
    for shared in ET.fromstring(response.content):
        if shared.get("machineIdentifier") != machine_id:
            continue
        invited = shared.find("invited")
        if invited is None:
            continue
        # An element without children is falsy: compare with None.
        settings = invited.find("sharingSettings")
        if settings is None:
            settings = shared.find(".//sharingSettings")
        if settings is None:
            continue
        result.append(Friend(
            id=invited.get("id") or shared.get("invitedId"),
            username=invited.get("username") or shared.get("invitedEmail") or "",
            name=invited.get("friendlyName") or invited.get("title") or invited.get("username") or "",
            settings=dict(settings.attrib),
        ))
    return result


def merge_filter(existing: str, labels: set[str]) -> str:
    """The filter with this app's excluded labels replaced by `labels`; everything else kept as is."""
    groups = [g for g in unquote(existing or "").split("&") if g]
    out, placed = [], False
    for group in groups:
        parts = []
        for part in group.split("|"):
            if not part.startswith("label!="):
                parts.append(part)
                continue
            kept = [v for v in part.removeprefix("label!=").split(",") if v and not v.startswith(PRIVATE_PREFIX)]
            values = kept + ([] if placed else sorted(labels))
            placed = True
            if values:
                parts.append("label!=" + ",".join(values))
        if parts:
            out.append("|".join(parts))
    if not placed and labels:
        out.append("label!=" + ",".join(sorted(labels)))
    return "&".join(out)


def wanted_filters(friend: Friend, hidden_from: dict[str, set[str]]) -> dict[str, str]:
    """New filterMovies/filterTelevision for a friend, given which labels they must not see."""
    labels = hidden_from.get(friend.id, set())
    return {name: merge_filter(friend.settings.get(name, ""), labels) for name in FILTERS}


def changed(friend: Friend, filters: dict[str, str]) -> bool:
    return any(unquote(friend.settings.get(name, "") or "") != value for name, value in filters.items())


def update(http: httpx.Client, token: str, client: str, friend: Friend, filters: dict[str, str]) -> None:
    """plex.tv replaces all of a friend's settings: send the current ones with the new filters."""
    s = friend.settings
    payload = {
        "invitedEmail": friend.username,
        "settings": {
            "allowChannels": s.get("allowChannels") == "1",
            "allowSync": s.get("allowSync") == "1",
            "allowCameraUpload": s.get("allowCameraUpload") == "1",
            "allowSubtitleAdmin": s.get("allowSubtitleAdmin") == "1",
            "allowTuners": int(s.get("allowTuners") or 0),
            "filterAll": s.get("filterAll") or None,
            "filterMusic": s.get("filterMusic") or "",
            "filterPhotos": s.get("filterPhotos") or "",
            **filters,
        },
    }
    try:
        response = http.post(f"{API}/sharing_settings", json=payload, timeout=TIMEOUT,
                             headers=_headers(token, client, "application/json"))
    except httpx.HTTPError as exc:
        raise SharingError(mask(f"Could not reach plex.tv: {type(exc).__name__}", [token])) from None
    if response.status_code not in (200, 201, 204):
        raise SharingError(f"plex.tv answered HTTP {response.status_code} when updating {friend.name}.")
