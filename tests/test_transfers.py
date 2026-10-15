import uuid

import pytest
from sqlalchemy import func, select

from app.models import Account, LedgerEntry, Transaction
from app.services import ledger_service

CLEAN = {"balance_mismatches": [], "unbalanced_transactions": []}


def open_account(client, headers, account_type="savings"):
    response = client.post("/accounts", json={"account_type": account_type}, headers=headers)
    return response.get_json()["id"]


def fund(client, headers, account_id, amount):
    response = client.post(
        f"/accounts/{account_id}/deposits", json={"amount": amount}, headers=headers
    )
    assert response.status_code == 201


def transfer(client, headers, from_id, to_id, amount):
    body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
    return client.post("/transfers", json=body, headers=headers)


def balance(client, headers, account_id):
    return client.get(f"/accounts/{account_id}", headers=headers).get_json()["balance"]


def test_transfer_moves_money_between_users(client, signup, db_session):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    fund(client, alice, a, 10_000)

    response = transfer(client, alice, a, b, 3_000)
    assert response.status_code == 201
    body = response.get_json()
    assert body["amount"] == 3_000
    assert body["balance_after"] == 7_000

    assert balance(client, alice, a) == 7_000
    assert balance(client, bob, b) == 3_000

    txn = db_session.scalars(select(Transaction).where(Transaction.type == "transfer")).one()
    entries = db_session.scalars(
        select(LedgerEntry).where(LedgerEntry.transaction_id == txn.id)
    ).all()
    assert sorted((str(e.account_id), e.direction, e.amount) for e in entries) == sorted(
        [(a, "debit", 3_000), (b, "credit", 3_000)]
    )

    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    assert settlement.balance == -10_000  # the transfer never touched it
    assert ledger_service.reconcile() == CLEAN


def test_transfer_insufficient_funds_rolls_back(client, signup, db_session):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    fund(client, alice, a, 1_000)

    response = transfer(client, alice, a, b, 5_000)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "insufficient_funds"

    assert balance(client, alice, a) == 1_000
    assert balance(client, bob, b) == 0
    transfers = db_session.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.type == "transfer")
    )
    assert transfers == 0


def test_cannot_transfer_from_someone_elses_account(client, signup):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    fund(client, alice, a, 5_000)

    response = transfer(client, bob, a, b, 1_000)  # Bob tries to pull from Alice
    assert response.status_code == 404
    assert balance(client, alice, a) == 5_000
    assert balance(client, bob, b) == 0


def test_destination_must_be_an_existing_customer_account(client, signup, db_session):
    alice = signup("alice")
    a = open_account(client, alice)
    fund(client, alice, a, 5_000)

    assert transfer(client, alice, a, str(uuid.uuid4()), 100).status_code == 404

    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    assert transfer(client, alice, a, str(settlement.id), 100).status_code == 404
    assert balance(client, alice, a) == 5_000


def test_cannot_transfer_to_same_account(client, signup):
    alice = signup("alice")
    a = open_account(client, alice)
    fund(client, alice, a, 5_000)

    response = transfer(client, alice, a, a, 100)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("amount", [0, "100"])
def test_invalid_transfer_amounts_rejected(client, signup, amount):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    assert transfer(client, alice, a, b, amount).status_code == 422


def test_transfer_requires_auth(client):
    body = {
        "from_account_id": str(uuid.uuid4()),
        "to_account_id": str(uuid.uuid4()),
        "amount": 100,
    }
    assert client.post("/transfers", json=body).status_code == 401


def test_transfer_between_own_accounts(client, signup):
    alice = signup("alice")
    savings = open_account(client, alice, "savings")
    current = open_account(client, alice, "current")
    fund(client, alice, savings, 4_000)

    assert transfer(client, alice, savings, current, 1_500).status_code == 201
    assert balance(client, alice, savings) == 2_500
    assert balance(client, alice, current) == 1_500


def test_books_balance_after_mixed_operations(client, signup, db_session):
    alice, bob = signup("alice"), signup("bob")
    a, b = open_account(client, alice), open_account(client, bob)
    fund(client, alice, a, 20_000)
    fund(client, bob, b, 5_000)

    assert transfer(client, alice, a, b, 7_500).status_code == 201
    assert transfer(client, bob, b, a, 1_000).status_code == 201
    withdrawal = client.post(f"/accounts/{b}/withdrawals", json={"amount": 2_000}, headers=bob)
    assert withdrawal.status_code == 201

    assert balance(client, alice, a) == 13_500
    assert balance(client, bob, b) == 9_500
    assert db_session.scalar(select(func.sum(Account.balance))) == 0  # conservation
    assert ledger_service.reconcile() == CLEAN