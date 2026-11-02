"""Hide secrets (API keys, tokens) found in URLs and headers.

Secrets are query parameters whose name looks like a key (access_key, api_key,
tmdb_key, token...), plus any value the user explicitly marks as secret.
"""

import re
from urllib.parse import parse_qsl, quote, unquote, urlsplit

MASK = "***"

_SECRET_NAME = re.compile(r"key|token|secret|passw|auth", re.IGNORECASE)


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def secrets_in_url(url: str) -> list[str]:
    query = urlsplit(url).query
    return [
        value
        for name, value in parse_qsl(query, keep_blank_values=True)
        if value and is_secret_name(name) and not value.startswith("{")
    ]


def mask(text: str, secrets: list[str] | tuple[str, ...]) -> str:
    """Replace every secret, raw or URL-encoded, with ***."""
    variants = set()
    for secret in secrets:
        if secret:
            variants.update({secret, quote(secret, safe=""), unquote(secret)})
    for variant in sorted(variants, key=len, reverse=True):
        text = text.replace(variant, MASK)
    return text


def mask_url(url: str, extra_secrets: list[str] | tuple[str, ...] = ()) -> str:
    return mask(url, [*secrets_in_url(url), *extra_secrets])


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: MASK if value else value for name, value in headers.items()}
