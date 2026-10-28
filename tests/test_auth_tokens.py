import pytest
import redis
from flask_jwt_extended import decode_token

from app.extensions import redis_ext
from app.services import token_service

CREDS = {"email": "alice@example.com", "username": "alice", "password": "s3cret-pass-1"}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tokens(client):
    assert client.post("/auth/register", json=CREDS).status_code == 201
    response = client.post(
        "/auth/login", json={"email": CREDS["email"], "password": CREDS["password"]}
    )
    return response.get_json()


def refresh(client, token):
    return client.post("/auth/refresh", headers=bearer(token))


def test_refresh_rotates_tokens(client, tokens):
    response = refresh(client, tokens["refresh_token"])
    assert response.status_code == 200
    new = response.get_json()
    assert new["refresh_token"] != tokens["refresh_token"]
    me = client.get("/auth/me", headers=bearer(new["access_token"]))
    assert me.status_code == 200


def test_reused_refresh_token_revokes_whole_family(client, tokens):
    new = refresh(client, tokens["refresh_token"]).get_json()

    replay = refresh(client, tokens["refresh_token"])  # attacker replays the old one
    assert replay.status_code == 401
    assert replay.get_json()["error"]["code"] == "token_revoked"

    # The legitimate newer tokens are dead too: the family was revoked.
    assert refresh(client, new["refresh_token"]).status_code == 401
    me = client.get("/auth/me", headers=bearer(new["access_token"]))
    assert me.status_code == 401
    assert me.get_json()["error"]["code"] == "token_revoked"


def test_access_token_cannot_be_used_to_refresh(client, tokens):
    response = refresh(client, tokens["access_token"])
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "invalid_token"


def test_logout_revokes_access_and_refresh(client, tokens):
    assert client.post("/auth/logout", headers=bearer(tokens["access_token"])).status_code == 204

    me = client.get("/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 401
    assert me.get_json()["error"]["code"] == "token_revoked"
    assert refresh(client, tokens["refresh_token"]).status_code == 401


def test_blocklist_entries_expire_on_their_own(client, tokens, app):
    client.post("/auth/logout", headers=bearer(tokens["access_token"]))
    with app.app_context():
        fid = decode_token(tokens["access_token"])["fid"]
    ttl = redis_ext.client.ttl(f"revoked:fid:{fid}")
    assert 0 < ttl <= 7 * 24 * 3600


def test_consume_token_is_single_use(app):
    import time

    with app.app_context():
        exp = int(time.time()) + 60
        assert token_service.consume_token("jti-1", exp) is True
        assert token_service.consume_token("jti-1", exp) is False


def test_redis_outage_fails_closed(client, tokens, monkeypatch):
    def boom(*args, **kwargs):
        raise redis.ConnectionError("redis is down")

    monkeypatch.setattr(redis_ext.client, "mget", boom)
    response = client.get("/auth/me", headers=bearer(tokens["access_token"]))
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "service_unavailable"
