import pytest
from sqlalchemy import func, select

from app.models import IdempotencyKey, LedgerEntry, Transaction
from app.services import idempotency_service, ledger_service

CLEAN = {"balance_mismatches": [], "unbalanced_transactions": []}


def open_account(client, headers):
    response = client.post("/accounts", json={"account_type": "savings"}, headers=headers)
    return response.get_json()["id"]


def _send(client, headers, url, body, key):
    merged = dict(headers)
    if key is not None:
        merged["Idempotency-Key"] = key
    return client.post(url, json=body, headers=merged)


def deposit(client, headers, account_id, amount, key=None):
    return _send(client, headers, f"/accounts/{account_id}/deposits", {"amount": amount}, key)


def withdraw(client, headers, account_id, amount, key=None):
    return _send(client, headers, f"/accounts/{account_id}/withdrawals", {"amount": amount}, key)


def transfer(client, headers, from_id, to_id, amount, key=None):
    body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
    return _send(client, headers, "/transfers", body, key)


def balance(client, headers, account_id):
    return client.get(f"/accounts/{account_id}", headers=headers).get_json()["balance"]


def count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def test_retry_with_same_key_credits_once(client, signup, db_session):
    alice = signup("alice")
    a = open_account(client, alice)

    first = deposit(client, alice, a, 5_000, key="k-1")
    second = deposit(client, alice, a, 5_000, key="k-1")

    assert first.status_code == second.status_code == 201
    assert second.get_json() == first.get_json()  # the stored response is replayed
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    assert balance(client, alice, a) == 5_000
    assert count(db_session, Transaction) == 1
    assert count(db_session, LedgerEntry) == 2
    assert ledger_service.reconcile() == CLEAN


def test_same_key_with_different_body_is_rejected(client, signup):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 5_000, key="k-1").status_code == 201

    response = deposit(client, alice, a, 6_000, key="k-1")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "idempotency_key_reuse"
    assert balance(client, alice, a) == 5_000


def test_same_key_on_a_different_account_is_rejected(client, signup):
    alice = signup("alice")
    a1, a2 = open_account(client, alice), open_account(client, alice)
    assert deposit(client, alice, a1, 5_000, key="k-1").status_code == 201

    response = deposit(client, alice, a2, 5_000, key="k-1")
    assert response.status_code == 422
    assert balance(client, alice, a2) == 0


def test_keys_are_scoped_per_user(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)

    first = deposit(client, alice, a, 1_000, key="same-key")
    second = deposit(client, bob, b, 2_000, key="same-key")

    assert first.status_code == second.status_code == 201
    assert "Idempotent-Replayed" not in second.headers  # Bob's key is his own
    assert balance(client, alice, a) == 1_000
    assert balance(client, bob, b) == 2_000


def test_transfer_retry_moves_money_once(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    assert deposit(client, alice, a, 10_000).status_code == 201

    first = transfer(client, alice, a, b, 3_000, key="t-1")
    second = transfer(client, alice, a, b, 3_000, key="t-1")

    assert first.status_code == second.status_code == 201
    assert second.get_json() == first.get_json()
    assert balance(client, alice, a) == 7_000
    assert balance(client, bob, b) == 3_000


def test_failed_request_does_not_consume_the_key(client, signup):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 1_000).status_code == 201

    failed = withdraw(client, alice, a, 5_000, key="w-1")
    assert failed.status_code == 422
    assert failed.get_json()["error"]["code"] == "insufficient_funds"

    assert deposit(client, alice, a, 10_000).status_code == 201
    retried = withdraw(client, alice, a, 5_000, key="w-1")  # same key, now affordable
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers
    assert balance(client, alice, a) == 6_000


def test_key_required_when_configured(app, client, signup, monkeypatch):
    alice = signup("alice")
    a = open_account(client, alice)
    assert deposit(client, alice, a, 100).status_code == 201  # optional by default

    monkeypatch.setitem(app.config, "IDEMPOTENCY_KEY_REQUIRED", True)
    response = deposit(client, alice, a, 100)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_idempotency_key"
    assert deposit(client, alice, a, 100, key="k-1").status_code == 201


@pytest.mark.parametrize("bad_key", ["", "x" * 256])
def test_invalid_keys_rejected(client, signup, bad_key):
    alice = signup("alice")
    a = open_account(client, alice)
    response = deposit(client, alice, a, 100, key=bad_key)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_idempotency_key"


def test_concurrent_duplicates_execute_once(app, client, signup, db_session, run_concurrently):
    alice = signup("alice")
    a = open_account(client, alice)

    def attempt():
        return app.test_client().post(
            f"/accounts/{a}/deposits",
            json={"amount": 5_000},
            headers={**alice, "Idempotency-Key": "race-1"},
        )

    results = run_concurrently([attempt for _ in range(8)])

    assert all(kind == "ok" for kind, _ in results)
    responses = [value for _, value in results]
    assert [r.status_code for r in responses] == [201] * 8
    assert len({r.get_json()["transaction_id"] for r in responses}) == 1
    replays = [r for r in responses if r.headers.get("Idempotent-Replayed") == "true"]
    assert len(replays) == 7  # exactly one request did the work

    assert balance(client, alice, a) == 5_000
    assert count(db_session, Transaction) == 1
    assert ledger_service.reconcile() == CLEAN


def test_key_and_money_commit_together_or_not_at_all(client, signup, db_session, monkeypatch):
    alice = signup("alice")
    a = open_account(client, alice)

    def crash(*args, **kwargs):
        raise RuntimeError("process dies right before the commit")

    monkeypatch.setattr(idempotency_service, "_store_response", crash)
    with pytest.raises(RuntimeError):
        deposit(client, alice, a, 5_000, key="k-crash")
    monkeypatch.undo()

    assert balance(client, alice, a) == 0
    assert count(db_session, Transaction) == 0
    assert count(db_session, IdempotencyKey) == 0  # no key without money, no money without key

    retried = deposit(client, alice, a, 5_000, key="k-crash")  # the retry runs for real, once
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers
    assert balance(client, alice, a) == 5_000
