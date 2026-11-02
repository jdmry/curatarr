from app.secrets import MASK, mask, mask_headers, mask_url, secrets_in_url

URL = "https://pp.example.com/poster?tmdb_id=194&access_key=s3cr%2Bt&tmdb_key=abc123&tg=medium&tk=1"


def test_finds_key_params():
    assert secrets_in_url(URL) == ["s3cr+t", "abc123"]


def test_mask_url_hides_raw_and_encoded_values():
    masked = mask_url(URL)
    assert "s3cr" not in masked and "abc123" not in masked
    assert f"access_key={MASK}" in masked and f"tmdb_key={MASK}" in masked
    assert "tmdb_id=194" in masked and "tk=1" in masked


def test_placeholders_are_not_secrets():
    assert secrets_in_url("https://x.test/p?api_key={key}") == []


def test_extra_secrets_in_path():
    assert mask_url("https://api.example.com/abcd-1234/imdb/poster-default/tt1.jpg", ["abcd-1234"]) == \
        f"https://api.example.com/{MASK}/imdb/poster-default/tt1.jpg"


def test_mask_in_log_text():
    assert mask("GET https://x.test/?token=zz9 failed", ["zz9"]) == f"GET https://x.test/?token={MASK} failed"


def test_mask_headers():
    assert mask_headers({"X-Api-Key": "abc", "Empty": ""}) == {"X-Api-Key": MASK, "Empty": ""}
