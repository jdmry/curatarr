"""Jinja filters."""

from datetime import UTC, datetime


def ago(value: str | None) -> str:
    """'3 min ago' from an SQLite CURRENT_TIMESTAMP (UTC) string."""
    if not value:
        return ""
    then = datetime.fromisoformat(value).replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - then).total_seconds())
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "min")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count > 1 and unit != 'min' else ''} ago"
    return value


def duration(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    seconds = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def until(value: datetime | None) -> str:
    """'in 2 h 15 min' until a future UTC datetime."""
    if value is None:
        return ""
    minutes = int((value - datetime.now(UTC)).total_seconds() // 60)
    if minutes < 1:
        return "any moment now"
    hours, minutes = divmod(minutes, 60)
    return f"in {hours} h {minutes} min" if hours else f"in {minutes} min"
