"""Download a poster image from a poster service."""

import time
from dataclasses import dataclass

import httpx

from app.branding import APP_NAME, APP_VERSION
from app.secrets import mask

MAX_BYTES = 20 * 1024 * 1024


@dataclass
class FetchResult:
    ok: bool
    content: bytes = b""
    content_type: str = ""
    status: int | None = None
    error: str | None = None
    elapsed: float = 0.0


def fetch_poster(
    url: str,
    headers: dict[str, str],
    timeout: float,
    secrets: list[str],
    transport: httpx.BaseTransport | None = None,
) -> FetchResult:
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
        ) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return FetchResult(False, error=f"No answer within {timeout:g} s.", elapsed=time.monotonic() - started)
    except httpx.HTTPError as exc:
        error = mask(f"{type(exc).__name__}: {exc}", secrets)
        return FetchResult(False, error=error, elapsed=time.monotonic() - started)

    elapsed = time.monotonic() - started
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    if response.status_code != 200:
        detail = mask(response.text[:200].strip(), secrets) if "text" in content_type or "json" in content_type else ""
        error = f"The service answered HTTP {response.status_code}." + (f" {detail}" if detail else "")
        return FetchResult(False, status=response.status_code, error=error, elapsed=elapsed)
    if not content_type.startswith("image/"):
        error = f"The service answered with {content_type or 'an unknown type'}, not an image."
        return FetchResult(False, status=200, error=error, elapsed=elapsed)
    if len(response.content) > MAX_BYTES:
        return FetchResult(False, status=200, error="The image is larger than 20 MB.", elapsed=elapsed)
    return FetchResult(True, response.content, content_type, 200, elapsed=elapsed)
