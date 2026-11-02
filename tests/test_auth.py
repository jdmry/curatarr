import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import connection
from app.main import create_app
from app.web import auth as auth_web

LOGIN = {"username": "admin", "password": "correct horse"}


@pytest.fixture
def anonymous(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(auth_web, "FAILED_LOGIN_DELAY", 0)


def test_password_hash():
    stored = auth.hash_password("secret pass")
    assert stored.startswith("scrypt$") and "secret" not in stored
    assert auth.verify_password("secret pass", stored) and not auth.verify_password("other", stored)
    assert not auth.verify_password("x", "garbage")


def test_pages_need_a_login(anonymous):
    response = anonymous.get("/posters/scope", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/login?next=/posters/scope"
    fragment = anonymous.get("/sync/card", headers={"HX-Request": "true"})
    assert fragment.headers["HX-Redirect"] == "/login?next=/sync/card" and fragment.text == ""
    assert anonymous.get("/plex/image?path=/library/metadata/1/thumb", follow_redirects=False).status_code == 303
    assert anonymous.post("/collections/sync/live", follow_redirects=False).status_code == 303
    assert anonymous.get("/health").json()["status"] == "ok"


def test_login_and_logout(anonymous):
    page = anonymous.get("/login?next=/collections").text
    assert 'name="next" value="/collections"' in page
    response = anonymous.post("/login", data={**LOGIN, "next": "/collections"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/collections"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=2592000" in cookie
    assert "Log out admin" in anonymous.get("/").text

    anonymous.post("/logout")
    assert anonymous.get("/", follow_redirects=False).status_code == 303


def test_next_stays_on_this_site(anonymous):
    response = anonymous.post("/login", data={**LOGIN, "next": "//evil.test/"}, follow_redirects=False)
    assert response.headers["location"] == "/"


def test_wrong_passwords_are_throttled(anonymous):
    for _ in range(5):
        assert "Wrong username or password" in anonymous.post("/login", data={**LOGIN, "password": "nope"}).text
    assert "Too many wrong passwords" in anonymous.post("/login", data=LOGIN).text


def test_posts_from_another_site_are_refused(client):
    response = client.post("/collections/sync/test", headers={"Origin": "https://evil.test"})
    assert response.status_code == 403
    assert client.post("/collections/sync/test", headers={"Origin": "http://testserver"}).status_code == 200


def test_missing_environment_blocks_the_app(env):
    app = create_app(dataclasses.replace(env, admin_username=None, admin_password=None))
    with TestClient(app) as client:
        page = client.get("/").text
        assert "Set ADMIN_USERNAME and ADMIN_PASSWORD" in page and 'name="password"' not in page
        assert 'name="password"' not in client.post("/login", data=LOGIN).text

    app = create_app(dataclasses.replace(env, admin_password="short"))
    with TestClient(app) as client:
        assert "ADMIN_PASSWORD is too short" in client.get("/login").text


def test_environment_only_makes_the_first_account(env, app, client):
    client.post("/settings/account", data={"username": "me", "current_password": "correct horse"})
    with TestClient(create_app(env)) as again:  # restarted with the same variables
        assert "Wrong username" in again.post("/login", data=LOGIN).text
        assert again.post("/login", data={**LOGIN, "username": "me"}, follow_redirects=False).status_code == 303


def test_change_password_logs_out_other_browsers(app, client):
    with TestClient(app) as other:
        other.post("/login", data=LOGIN)
        assert other.get("/", follow_redirects=False).status_code == 200

        html = client.post("/settings/account", data={"username": "admin", "current_password": "wrong"}).text
        assert "current password is wrong" in html
        data = {"username": "admin", "current_password": "correct horse", "new_password": "new password!",
                "confirm_password": "new password!"}
        assert "Saved." in client.post("/settings/account", data=data).text
        assert other.get("/", follow_redirects=False).status_code == 303
        assert client.get("/", follow_redirects=False).status_code == 200
    with connection(app.state.db_path) as conn:
        assert auth.check_login(conn, "admin", "new password!")


def test_account_page(client):
    html = client.get("/settings/account").text
    assert 'value="admin"' in html and "python -m app.reset_password" in html
    short = {"username": "admin", "current_password": "correct horse", "new_password": "x", "confirm_password": "x"}
    assert "at least 8 characters" in client.post("/settings/account", data=short).text


def test_reset_password_command(env, app, client, monkeypatch):
    from app import reset_password

    monkeypatch.setattr(reset_password, "load_env", lambda: env)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(reset_password.getpass, "getpass", lambda prompt: "brand new pass")
    assert reset_password.main() == 0
    assert client.get("/", follow_redirects=False).status_code == 303  # sessions ended
    with connection(app.state.db_path) as conn:
        assert auth.check_login(conn, "admin", "brand new pass")
