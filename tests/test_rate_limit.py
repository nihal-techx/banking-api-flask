import pytest
import redis

from app.extensions import redis_ext
from app.services import rate_limit_service


def login(client, email="nobody@example.com", password="wrong-password-1", headers=None):
    return client.post(
        "/auth/login", json={"email": email, "password": password}, headers=headers or {}
    )


def test_login_is_throttled_per_ip_and_email(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "RATE_LIMIT_LOGIN_ATTEMPTS", 3)

    assert [login(client).status_code for _ in range(3)] == [401, 401, 401]
    throttled = login(client)

    assert throttled.status_code == 429
    assert throttled.get_json()["error"]["code"] == "rate_limited"
    assert 1 <= int(throttled.headers["Retry-After"]) <= 60
    assert login(client, email="someone.else@example.com").status_code == 401  # separate bucket


def test_login_is_throttled_per_ip_across_emails(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "RATE_LIMIT_LOGIN_IP_ATTEMPTS", 2)

    assert login(client, email="a@example.com").status_code == 401
    assert login(client, email="b@example.com").status_code == 401
    assert login(client, email="c@example.com").status_code == 429


def test_register_is_throttled_per_ip(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "RATE_LIMIT_REGISTER_IP_ATTEMPTS", 2)

    def register(name):
        body = {"email": f"{name}@example.com", "username": name, "password": "s3cret-pass-1"}
        return client.post("/auth/register", json=body)

    assert register("first").status_code == 201
    assert register("second").status_code == 201
    assert register("third").status_code == 429


def test_counters_expire_with_the_window(client):
    login(client)
    keys = list(redis_ext.client.scan_iter("ratelimit:*"))
    assert len(keys) == 2  # one per bucket: the IP and the (IP, email) pair
    for key in keys:
        assert 0 < redis_ext.client.ttl(key) <= 60
        assert "nobody@example.com" not in key  # identifiers are hashed


def test_rate_limiter_fails_open_when_redis_is_down(client, monkeypatch):
    def down(*args, **kwargs):
        raise redis.ConnectionError("redis is down")

    monkeypatch.setattr(redis_ext.client, "pipeline", down)
    assert login(client).status_code == 401  # a normal answer, not a 429 or a 5xx


def test_rate_limiting_can_be_disabled(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setitem(app.config, "RATE_LIMIT_LOGIN_ATTEMPTS", 1)
    assert all(login(client).status_code == 401 for _ in range(5))


@pytest.mark.parametrize(
    "trusted,forwarded,expected",
    [
        (0, "1.2.3.4", "10.0.0.1"),  # no trusted proxy: the header is ignored
        (1, "6.6.6.6, 1.2.3.4", "1.2.3.4"),  # the last entry was added by our proxy
        (2, "6.6.6.6, 1.2.3.4, 10.9.9.9", "1.2.3.4"),  # second from the right
        (1, "", "10.0.0.1"),  # no header at all: fall back to the socket address
        (3, "1.2.3.4", "10.0.0.1"),  # fewer entries than trusted proxies: do not guess
    ],
)
def test_client_ip_trusts_only_the_configured_number_of_proxies(
    app, monkeypatch, trusted, forwarded, expected
):
    monkeypatch.setitem(app.config, "TRUSTED_PROXY_COUNT", trusted)
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    with app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        assert rate_limit_service.client_ip() == expected


def test_a_spoofed_forwarded_header_cannot_evade_the_limit(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "TRUSTED_PROXY_COUNT", 1)
    monkeypatch.setitem(app.config, "RATE_LIMIT_LOGIN_ATTEMPTS", 2)

    statuses = [
        # the attacker rotates the leftmost value, but our proxy always appends the real IP
        login(client, headers={"X-Forwarded-For": f"9.9.9.{i}, 1.2.3.4"}).status_code
        for i in range(3)
    ]
    assert statuses == [401, 401, 429]


def test_throttled_endpoints_document_429(client):
    spec = client.get("/openapi/openapi.json").get_json()
    for path in ("/auth/login", "/auth/register"):
        assert "429" in spec["paths"][path]["post"]["responses"], path
