from app.branding import APP_NAME


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["app"] == APP_NAME


def test_plex_banner_until_configured(client):
    html = client.get("/").text
    assert "Connect your Plex server" in html and 'href="/settings/plex"' in html
    assert "Connect your Plex server" not in client.get("/settings/plex").text
    assert client.get("/settings", follow_redirects=False).headers["location"] == "/settings/plex"


def test_static_urls_carry_content_hash(client):

    html = client.get("/settings/plex").text
    assert '/static/app.css?v=' in html and '/static/vendor/htmx.min.js?v=' in html
