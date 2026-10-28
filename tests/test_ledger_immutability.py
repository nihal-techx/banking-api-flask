import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services import ledger_service

CLEAN = {"balance_mismatches": [], "unbalanced_transactions": []}


@pytest.fixture
def posted(bank, signup, db_session):
    alice = signup("alice")
    account_id = bank.open_account(alice)
    bank.fund(alice, account_id, 5_000)
    return account_id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_entries SET amount = amount + 1",
        "UPDATE ledger_entries SET balance_after = 0",
        "DELETE FROM ledger_entries",
        "UPDATE transactions SET type = 'withdrawal'",
        "DELETE FROM transactions",
    ],
)
def test_ledger_rows_cannot_be_changed_or_deleted(db_session, posted, statement):
    with pytest.raises(IntegrityError, match="append-only"):
        db_session.execute(text(statement))
    db_session.rollback()


def test_failed_tampering_leaves_the_books_intact(db_session, posted):
    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM ledger_entries"))
    db_session.rollback()

    assert ledger_service.reconcile() == CLEAN
