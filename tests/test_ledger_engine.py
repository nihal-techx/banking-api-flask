import pytest
from sqlalchemy import func, select, text

from app.errors import InsufficientFundsError
from app.extensions import db
from app.models import Account, LedgerEntry, Transaction, User
from app.services import ledger_service, money_service
from app.services.ledger_service import Entry, LedgerError


def make_account(db_session, username="alice"):
    user = User(email=f"{username}@example.com", username=username, password_hash="x")
    db_session.add(user)
    db_session.flush()
    account = Account(owner_id=user.id, account_type="savings")
    db_session.add(account)
    db_session.flush()
    return user, account


@pytest.mark.parametrize(
    "case", ["unbalanced", "single_entry", "duplicate_account", "non_positive"]
)
def test_post_transaction_rejects_invalid_postings(db_session, case):
    _, account = make_account(db_session)
    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    entries = {
        "unbalanced": [Entry(settlement.id, "debit", 100), Entry(account.id, "credit", 90)],
        "single_entry": [Entry(account.id, "credit", 100)],
        "duplicate_account": [Entry(account.id, "debit", 100), Entry(account.id, "credit", 100)],
        "non_positive": [Entry(settlement.id, "debit", 0), Entry(account.id, "credit", 0)],
    }[case]

    with pytest.raises(LedgerError):
        ledger_service.post_transaction("deposit", entries)
    assert db_session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_reconcile_detects_balance_tampering(db_session):
    user, account = make_account(db_session)
    db_session.commit()
    money_service.deposit(user.id, account.id, 1_000)

    db_session.execute(
        text("UPDATE accounts SET balance = 999999 WHERE id = :id"), {"id": account.id}
    )
    db_session.commit()

    mismatches = ledger_service.reconcile()["balance_mismatches"]
    assert [m["account_id"] for m in mismatches] == [account.id]
    assert mismatches[0]["cached_balance"] == 999_999
    assert mismatches[0]["ledger_balance"] == 1_000


def test_reconcile_detects_unbalanced_transaction(db_session):
    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    txn = Transaction(type="deposit")
    db_session.add(txn)
    db_session.flush()
    db_session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=settlement.id,
            direction="credit",
            amount=500,
            balance_after=500,
        )
    )
    db_session.commit()

    unbalanced = ledger_service.reconcile()["unbalanced_transactions"]
    assert [t["transaction_id"] for t in unbalanced] == [txn.id]


def test_posting_uses_fresh_balance_not_stale_identity_map(db_session):
    user, account = make_account(db_session)
    db_session.commit()
    money_service.deposit(user.id, account.id, 1_000)

    assert account.balance == 1_000  # now cached in this session's identity map

    # A "concurrent" writer on its own connection drops the balance to 400.
    with db.engine.begin() as other_connection:
        other_connection.execute(
            text("UPDATE accounts SET balance = 400 WHERE id = :id"), {"id": account.id}
        )

    # With a stale read this would succeed (1000 >= 500). With populate_existing it must fail.
    with pytest.raises(InsufficientFundsError):
        money_service.withdraw(user.id, account.id, 500)