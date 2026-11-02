from dataclasses import replace

from fastapi.testclient import TestClient

from app.db import connection, migrate
from app.main import create_app
from app.settings_store import get_setting, seed_setting, set_setting


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "test.db"
    version = migrate(path)
    assert version >= 1
    assert migrate(path) == version


def test_settings_round_trip(tmp_path):
    path = tmp_path / "test.db"
    migrate(path)
    with connection(path) as conn:
        assert get_setting(conn, "missing", "default") == "default"
        set_setting(conn, "a", {"x": [1, 2]})
        set_setting(conn, "a", {"x": [3]})
        seed_setting(conn, "a", "ignored")
        seed_setting(conn, "b", True)
    with connection(path) as conn:
        assert get_setting(conn, "a") == {"x": [3]}
        assert get_setting(conn, "b") is True


def test_env_values_seed_but_do_not_override(env):
    env = replace(env, plex_url="http://plex.local:32400/", plex_token="env-token")
    app = create_app(env)
    with TestClient(app):
        pass
    with connection(app.state.db_path) as conn:
        assert get_setting(conn, "plex.url") == "http://plex.local:32400"
        set_setting(conn, "plex.token", "ui-token")
    with TestClient(create_app(env)):
        pass
    with connection(app.state.db_path) as conn:
        assert get_setting(conn, "plex.token") == "ui-token"


def test_connection_can_close_in_another_thread(tmp_path):
    import threading

    path = tmp_path / "test.db"
    migrate(path)
    context = connection(path)
    conn = context.__enter__()
    errors = []

    def finish():
        try:
            conn.execute("SELECT 1")
            context.__exit__(None, None, None)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=finish)
    thread.start()
    thread.join()
    assert errors == []


def test_scope_moves_into_the_lists(tmp_path, monkeypatch):
    """A 0.3 install: the collections picked for posters keep their service as a list setting."""
    from app import db

    path = tmp_path / "old.db"
    old = tmp_path / "migrations"
    old.mkdir()
    for file in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(file.name.split("_", 1)[0]) <= 9:
            (old / file.name).write_text(file.read_text())
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    migrate(path)
    with connection(path) as conn:
        conn.execute("INSERT INTO poster_sources (id, name, url_template) VALUES (5, 'RPDB', 'https://r.test/x')")
        for key, name in (("100", "Picked"), ("200", "Default one"), ("300", "Not picked")):
            conn.execute("INSERT INTO lists (name, url, library_key, library_title, collection_key)"
                         " VALUES (?, 'mdblist:1', '1', 'Movies', ?)", (name, key))
        conn.execute("INSERT INTO scope (library_key, library_title, collection_key, collection_title, source_id)"
                     " VALUES ('1', 'Movies', '100', 'Picked', 5), ('1', 'Movies', '200', 'Default one', NULL)")
        set_setting(conn, "schedule.enabled", True)
        set_setting(conn, "lists_schedule.enabled", True)
    monkeypatch.undo()
    migrate(path)
    with connection(path) as conn:
        rows = conn.execute("SELECT name, posters, poster_source_id FROM lists ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [("Picked", 1, 5), ("Default one", 1, None), ("Not picked", 0, None)]
        assert get_setting(conn, "schedule.enabled") is None and get_setting(conn, "lists_schedule.enabled") is True
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'scope'").fetchone() is None

