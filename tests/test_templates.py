import re
from pathlib import Path

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"
REQUEST_TAG = re.compile(r"<[a-z]+\b[^>]*\bhx-(?:get|post)=[^>]*>", re.S)


def test_htmx_requests_say_where_they_go():
    """hx-target is not inherited (disableInheritance), so a button in a form would swap the response into itself."""
    loose = [
        f"{path.relative_to(TEMPLATES)}: {' '.join(tag.split())[:100]}"
        for path in TEMPLATES.rglob("*.html")
        for tag in REQUEST_TAG.findall(path.read_text())
        if "hx-target" not in tag and 'hx-swap="outerHTML"' not in tag
    ]
    assert loose == []
