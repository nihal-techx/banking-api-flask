import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Account, LedgerEntry, Transaction, User
from app.services import ledger_service


def make_user():
    return User(email="a@example.com", username="alice", password_hash="x")


def test_system_account_may_go_negative(db_session):
    account = ledger_service.ensure_system_account("SETTLEMENT")
    account.balance = -500
    db_session.commit()
    assert db_session.get(Account, account.id).balance == -500


@pytest.mark.parametrize(
    "account_type,has_owner,system_code",
    [
        ("savings", False, None),  # customer account without an owner
        ("savings", True, "SETTLEMENT"),  # customer account carrying a system code
        ("system", False, None),  # system account without a code
        ("system", True, "SETTLEMENT"),  # system account with an owner
    ],
)
def test_account_owner_must_match_type(db_session, account_type, has_owner, system_code):
    owner_id = None
    if has_owner:
        user = make_user()
        db_session.add(user)
        db_session.flush()
        owner_id = user.id
    db_session.add(Account(account_type=account_type, owner_id=owner_id, system_code=system_code))
    with pytest.raises(IntegrityError):
        db_session.flush()


def _txn_and_account(db_session):
    account = ledger_service.ensure_system_account("SETTLEMENT")
    txn = Transaction(type="deposit")
    db_session.add(txn)
    db_session.flush()
    return txn, account


def test_ledger_entry_amount_must_be_positive(db_session):
    txn, account = _txn_and_account(db_session)
    db_session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=account.id,
            direction="credit",
            amount=0,
            balance_after=0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_ledger_entry_direction_must_be_valid(db_session):
    txn, account = _txn_and_account(db_session)
    db_session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=account.id,
            direction="other",
            amount=100,
            balance_after=100,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_ensure_system_account_is_idempotent(db_session):
    first = ledger_service.ensure_system_account("SETTLEMENT")
    second = ledger_service.ensure_system_account("SETTLEMENT")
    assert first.id == second.id
    assert db_session.query(Account).filter_by(account_type="system").count() == 1
