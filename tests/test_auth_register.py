from sqlalchemy import select

from app.models import User

VALID = {"email": "Alice@Example.com", "username": "alice", "password": "s3cret-pass-1"}


def test_register_success(client, db_session):
    response = client.post("/auth/register", json=VALID)
    assert response.status_code == 201
    body = response.get_json()
    assert body["email"] == "alice@example.com"  # normalized
    assert "password" not in body and "password_hash" not in body

    stored = db_session.scalars(select(User)).one()
    assert stored.password_hash.startswith("$argon2id$")
    assert stored.password_hash != VALID["password"]


def test_duplicate_email_is_conflict_even_with_different_case(client):
    assert client.post("/auth/register", json=VALID).status_code == 201
    second = {**VALID, "email": "ALICE@example.com", "username": "alice2"}
    response = client.post("/auth/register", json=second)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


def test_weak_password_rejected_and_not_echoed(client):
    payload = {**VALID, "password": "short"}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"
    assert "short" not in response.get_data(as_text=True).replace("too short", "")


def test_invalid_email_rejected(client):
    response = client.post("/auth/register", json={**VALID, "email": "not-an-email"})
    assert response.status_code == 422
