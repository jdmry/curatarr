import pytest
from fastapi.testclient import TestClient

from app.config import Env
from app.main import create_app


@pytest.fixture
def env(tmp_path):
    return Env(data_dir=tmp_path, port=8080, plex_url=None, plex_token=None, log_level="info", update_check=False,
               admin_username="admin", admin_password="correct horse")


@pytest.fixture
def app(env):
    return create_app(env)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "correct horse"})
        yield client
