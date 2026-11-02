"""Static file URLs with a content hash, so browsers never keep an old copy."""

import hashlib
from functools import cache
from pathlib import Path

STATIC_DIR = Path(__file__).parent.parent / "static"


@cache
def asset(path: str) -> str:
    digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:12]
    return f"/static/{path}?v={digest}"
