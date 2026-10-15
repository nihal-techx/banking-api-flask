import uuid

from sqlalchemy import select

from app.errors import NotFoundError
from app.extensions import db
from app.models import Account, LedgerEntry, Transaction
from app.services import account_service, ledger_service
from app.services.ledger_service import SETTLEMENT, Entry


def _commit_posting(txn_type: str, entries: list[Entry]) -> Transaction:
    """Post and commit as one unit; roll everything back on any error."""
    try:
        txn = ledger_service.post_transaction(txn_type, entries)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return txn


def _entry_for(txn: Transaction, account_id: uuid.UUID) -> LedgerEntry:
    return next(entry for entry in txn.entries if entry.account_id == account_id)


def _settle(txn_type: str, owner_id: uuid.UUID, account_id: uuid.UUID, customer_direction: str, amount: int) -> LedgerEntry:
    account = account_service.get_owned_account(owner_id, account_id)  # 404 if not theirs
    settlement = ledger_service.ensure_system_account(SETTLEMENT)
    settlement_direction = "debit" if customer_direction == "credit" else "credit"
    txn = _commit_posting(
        txn_type,
        [
            Entry(settlement.id, settlement_direction, amount),
            Entry(account.id, customer_direction, amount),
        ],
    )
    return _entry_for(txn, account_id)


def deposit(owner_id: uuid.UUID, account_id: uuid.UUID, amount: int) -> LedgerEntry:
    return _settle("deposit", owner_id, account_id, "credit", amount)


def withdraw(owner_id: uuid.UUID, account_id: uuid.UUID, amount: int) -> LedgerEntry:
    return _settle("withdrawal", owner_id, account_id, "debit", amount)


def transfer(owner_id: uuid.UUID, from_account_id: uuid.UUID, to_account_id: uuid.UUID, amount: int) -> LedgerEntry:
    source = account_service.get_owned_account(owner_id, from_account_id)  # must be theirs
    destination = db.session.scalar(
        select(Account).where(Account.id == to_account_id, Account.account_type != "system")
    )
    if destination is None:
        raise NotFoundError("Destination account not found")
    txn = _commit_posting(
        "transfer",
        [Entry(source.id, "debit", amount), Entry(destination.id, "credit", amount)],
    )
    return _entry_for(txn, from_account_id)