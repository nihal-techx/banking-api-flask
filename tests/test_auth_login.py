from datetime import timedelta

from flask_jwt_extended import create_access_token

CREDS = {"email": "alice@example.com", "username": "alice", "password": "s3cret-pass-1"}


def register(client):
    assert client.post("/auth/register", json=CREDS).status_code == 201


def login(client, email=CREDS["email"], password=CREDS["password"]):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_tokens_and_me_works(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    tokens = response.get_json()
    assert tokens["token_type"] == "bearer"
    me = client.get("/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.get_json()["email"] == CREDS["email"]


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client)
    wrong = login(client, password="not-the-password")
    unknown = login(client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


def test_me_requires_token(client):
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "missing_token"


def test_garbage_token_rejected(client):
    response = client.get("/auth/me", headers=bearer("not.a.jwt"))
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "invalid_token"


def test_refresh_token_cannot_access_protected_route(client):
    register(client)
    refresh = login(client).get_json()["refresh_token"]
    response = client.get("/auth/me", headers=bearer(refresh))
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "invalid_token"


def test_expired_token_rejected(client, app):
    with app.app_context():
        token = create_access_token("some-user", expires_delta=timedelta(seconds=-1))
    response = client.get("/auth/me", headers=bearer(token))
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "token_expired"
