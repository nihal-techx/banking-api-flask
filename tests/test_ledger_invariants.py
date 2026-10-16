import uuid

import pytest

from app.models import Account, User
from app.services import ledger_service
from app.services.ledger_service import Entry, LedgerError


def make_account(db_session, username, currency="INR"):
    user = User(email=f"{username}@example.com", username=username, password_hash="x")
    db_session.add(user)
    db_session.flush()
    account = Account(owner_id=user.id, account_type="savings", currency=currency)
    db_session.add(account)
    db_session.flush()
    return account


@pytest.mark.parametrize("case", ["invalid_direction", "unknown_account", "cross_currency"])
def test_engine_rejects_postings_that_break_ledger_invariants(db_session, case):
    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    inr = make_account(db_session, "alice")
    usd = make_account(db_session, "bob", currency="USD")
    entries = {
        "invalid_direction": [Entry(settlement.id, "debit", 100), Entry(inr.id, "sideways", 100)],
        "unknown_account": [Entry(settlement.id, "debit", 100), Entry(uuid.uuid4(), "credit", 100)],
        "cross_currency": [Entry(inr.id, "debit", 100), Entry(usd.id, "credit", 100)],
    }[case]

    with pytest.raises(LedgerError):
        ledger_service.post_transaction("deposit", entries)