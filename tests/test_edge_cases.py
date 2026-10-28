import uuid

from sqlalchemy import text

from app.extensions import db


def test_token_for_a_deleted_user_is_rejected(client, signup, db_session):
    alice = signup("alice")
    db_session.execute(text("DELETE FROM users"))
    db_session.commit()

    response = client.get("/auth/me", headers=alice)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_duplicate_key_in_flight_times_out_as_busy_then_recovers(
    app, signup, bank, db_session, monkeypatch
):
    alice = signup("alice")
    account_id = bank.open_account(alice)
    user_id = db_session.scalar(text("SELECT id FROM users"))
    monkeypatch.setitem(app.config, "LEDGER_LOCK_TIMEOUT_MS", 300)

    # Another request has inserted this key but has not committed yet.
    other = db.engine.connect()
    in_flight = other.begin()
    try:
        other.execute(
            text(
                "INSERT INTO idempotency_keys (id, user_id, key, request_hash) "
                "VALUES (:id, :user_id, 'busy-key', 'some-hash')"
            ),
            {"id": uuid.uuid4(), "user_id": user_id},
        )
        response = bank.deposit(alice, account_id, 100, key="busy-key")
    finally:
        in_flight.rollback()
        other.close()

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "busy"

    retry = bank.deposit(alice, account_id, 100, key="busy-key")  # the other request died
    assert retry.status_code == 201
    assert bank.balance(alice, account_id) == 100
