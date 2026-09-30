import io
import json
import urllib.request


import bricklink
from bricklink import Credentials, oauth_header


def test_oauth_signature_matches_published_example():
    """Twitter's published OAuth 1.0a signing walkthrough."""
    creds = Credentials("xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                        "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
                        "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE")
    header = oauth_header(
        "POST", "https://api.twitter.com/1.1/statuses/update.json", creds,
        params={"include_entities": "true",
                "status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp="1318622958")
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in header


CREDS = Credentials("ck", "cs", "t", "ts")


def fake_api(monkeypatch, responses):
    """Serve canned BrickLink JSON by URL path; records the paths asked for."""
    calls = []

    def urlopen(req, timeout):
        path = req.full_url.removeprefix(bricklink.API_BASE)
        assert req.headers["Authorization"].startswith("OAuth ")
        calls.append(path)
        return io.BytesIO(json.dumps(responses[path]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


OK = {"code": 200, "message": "OK"}


def test_lookup_fetches_then_caches(monkeypatch, tmp_path):
    calls = fake_api(monkeypatch, {
        "/item_mapping/4211388": {"meta": OK, "data": [
            {"item": {"no": "3004", "type": "PART"}, "color_name": "Light Bluish Gray"}]},
        "/items/PART/3004": {"meta": OK, "data": {"no": "3004", "weight": "0.82"}},
        "/item_mapping/9999999": {"meta": {"code": 404, "message": "RESOURCE_NOT_FOUND"}},
    })
    cache = str(tmp_path / "cache.json")
    found, error = bricklink.lookup(["4211388", "9999999"], CREDS, cache)
    assert error is None
    assert found["4211388"] == bricklink.PartInfo("3004", "Light Bluish Gray", 0.82)
    assert found["9999999"].weight is None
    assert len(calls) == 3

    calls.clear()
    found, _ = bricklink.lookup(["4211388", "9999999"], CREDS, cache)
    assert calls == []  # both served from cache (the miss is retried only after a week)
    assert found["4211388"].weight == 0.82


def test_zero_weight_means_unknown(monkeypatch, tmp_path):
    fake_api(monkeypatch, {
        "/item_mapping/6584302": {"meta": OK, "data": [
            {"item": {"no": "1234", "type": "PART"}, "color_name": "Black"}]},
        "/items/PART/1234": {"meta": OK, "data": {"weight": "0.00"}},
    })
    found, _ = bricklink.lookup(["6584302"], CREDS, str(tmp_path / "c.json"))
    assert found["6584302"].weight is None and found["6584302"].color == "Black"


def test_auth_failure_is_reported_not_cached(monkeypatch, tmp_path):
    fake_api(monkeypatch, {"/item_mapping/4211388": {"meta": {
        "code": 401, "message": "BAD_OAUTH_REQUEST", "description": "TOKEN_IP_MISMATCHED"}}})
    found, error = bricklink.lookup(["4211388"], CREDS, str(tmp_path / "c.json"))
    assert found == {} and "TOKEN_IP_MISMATCHED" in error
