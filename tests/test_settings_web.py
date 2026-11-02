import pytest

from app.db import connection
from app.plex import client as plex
from app.plex.client import ConnectionCheck, Library, PlexConnection, load_connection


@pytest.fixture
def checks(monkeypatch):
    calls = []

    def fake_check(conn, with_thumbs=False):
        calls.append(conn)
        return ConnectionCheck(True, server_name="Home", version="1.41", libraries=[Library("1", "Films", "movie", 42)])

    monkeypatch.setattr(plex, "check_connection", fake_check)
    return calls


def saved(app):
    with connection(app.state.db_path) as conn:
        return load_connection(conn)


def test_settings_page(client):
    response = client.get("/settings/plex")
    assert response.status_code == 200
    assert "Plex server" in response.text


def test_save_requires_url_and_token(client, app, checks):
    response = client.post("/settings/plex", data={"url": "http://plex:32400", "token": ""})
    assert "required" in response.text
    assert saved(app) is None
    assert checks == []


def test_save_then_keep_token(client, app, checks):
    response = client.post("/settings/plex", data={"url": "http://plex:32400/", "token": "abc"})
    assert "Saved." in response.text and "Home" in response.text and "Films" in response.text
    assert saved(app) == PlexConnection("http://plex:32400", "abc")

    client.post("/settings/plex", data={"url": "http://other:32400", "token": ""})
    assert saved(app) == PlexConnection("http://other:32400", "abc")

    page = client.get("/settings/plex").text
    assert "abc" not in page
    assert "http://other:32400" in page


def test_test_button_does_not_save(client, app, checks):
    response = client.post("/settings/plex/test", data={"url": "http://plex:32400", "token": "abc"})
    assert "Connected to" in response.text
    assert checks == [PlexConnection("http://plex:32400", "abc")]
    assert saved(app) is None


def test_check_rejects_url_without_scheme():
    assert not plex.check_connection(PlexConnection("192.168.1.10:32400", "t")).ok


def test_check_reports_bad_token(monkeypatch):
    from plexapi.exceptions import Unauthorized

    def refuse(connection):
        raise Unauthorized("(401) unauthorized; http://plex:32400/?X-Plex-Token=secret")

    monkeypatch.setattr(plex, "connect", refuse)
    check = plex.check_connection(PlexConnection("http://plex:32400", "secret"))
    assert not check.ok
    assert "token" in check.error and "secret" not in check.error
