import uuid

import pytest
from sqlalchemy import func, select

from app.models import LedgerEntry, Transaction
from app.services import ledger_service


def open_account(client, headers):
    response = client.post("/accounts", json={"account_type": "savings"}, headers=headers)
    return response.get_json()["id"]


def deposit(client, headers, account_id, amount):
    return client.post(f"/accounts/{account_id}/deposits", json={"amount": amount}, headers=headers)


def withdraw(client, headers, account_id, amount):
    return client.post(f"/accounts/{account_id}/withdrawals", json={"amount": amount}, headers=headers)


def count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def test_deposit_credits_account_and_writes_balanced_entries(client, signup, db_session):
    alice = signup("alice")
    account_id = open_account(client, alice)

    response = deposit(client, alice, account_id, 10_000)
    assert response.status_code == 201
    body = response.get_json()
    assert body["type"] == "deposit"
    assert body["amount"] == 10_000
    assert body["balance_after"] == 10_000

    entries = db_session.scalars(select(LedgerEntry)).all()
    assert sorted((e.direction, e.amount) for e in entries) == [
        ("credit", 10_000),
        ("debit", 10_000),
    ]
    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    assert settlement.balance == -10_000  # mirrors total customer money
    assert ledger_service.reconcile() == {"balance_mismatches": [], "unbalanced_transactions": []}


def test_withdraw_debits_account(client, signup):
    alice = signup("alice")
    account_id = open_account(client, alice)
    deposit(client, alice, account_id, 10_000)

    response = withdraw(client, alice, account_id, 4_000)
    assert response.status_code == 201
    assert response.get_json()["balance_after"] == 6_000
    assert client.get(f"/accounts/{account_id}", headers=alice).get_json()["balance"] == 6_000


def test_withdraw_beyond_balance_rejected_and_rolled_back(client, signup, db_session):
    alice = signup("alice")
    account_id = open_account(client, alice)
    deposit(client, alice, account_id, 1_000)

    response = withdraw(client, alice, account_id, 2_000)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "insufficient_funds"

    assert client.get(f"/accounts/{account_id}", headers=alice).get_json()["balance"] == 1_000
    assert count(db_session, Transaction) == 1  # only the deposit
    assert count(db_session, LedgerEntry) == 2


def test_cannot_move_money_on_someone_elses_account(client, signup, db_session):
    alice, bob = signup("alice"), signup("bob")
    account_id = open_account(client, alice)

    assert deposit(client, bob, account_id, 500).status_code == 404
    assert withdraw(client, bob, account_id, 500).status_code == 404
    assert count(db_session, Transaction) == 0


@pytest.mark.parametrize("amount", [0, -5, "100", 10.5, 2_000_000_000])
def test_invalid_amounts_rejected(client, signup, amount):
    alice = signup("alice")
    account_id = open_account(client, alice)
    assert deposit(client, alice, account_id, amount).status_code == 422


def test_money_endpoints_require_auth(client):
    account_id = uuid.uuid4()
    assert client.post(f"/accounts/{account_id}/deposits", json={"amount": 100}).status_code == 401
    assert client.post(f"/accounts/{account_id}/withdrawals", json={"amount": 100}).status_code == 401