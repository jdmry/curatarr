import httpx

from app import updates
from app.updates import UpdateCheck, parse


def test_parse():
    assert parse("v0.10.2") == (0, 10, 2) and parse("0.1") == (0, 1) and parse("edge") is None


def test_newer_release_shows_in_the_sidebar(client, app, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"tag_name": "v9.0.0"})

    monkeypatch.setattr(updates.httpx, "get", fake_get)
    check = UpdateCheck(enabled=True, current="0.1.2")
    check.newer()  # starts the check in the background
    with check._lock:  # wait for it
        pass
    assert check.newer() == "9.0.0" and len(calls) == 1  # checked once a day only

    app.state.templates.env.globals["newer_version"] = check.newer
    html = client.get("/").text
    assert "Update available: 9.0.0" in html and "/releases/tag/v9.0.0" in html


def test_no_check_when_disabled_or_up_to_date(monkeypatch):
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no call")))
    assert UpdateCheck(enabled=False).newer() is None
    check = UpdateCheck(enabled=False, current="1.0.0")
    check.latest = "1.0.0"
    assert check.newer() is None


def test_version_links_to_releases(client):
    html = client.get("/").text
    assert "https://github.com/jdmry/curatarr/releases" in html and "Update available" not in html
