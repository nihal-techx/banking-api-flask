import uuid

from app.extensions import db
from app.models import LedgerEntry
from app.services import account_service, ledger_service
from app.services.ledger_service import SETTLEMENT, Entry


def _post(txn_type: str, owner_id: uuid.UUID, account_id: uuid.UUID, customer_direction: str, amount: int) -> LedgerEntry:
    account = account_service.get_owned_account(owner_id, account_id)  # 404 if not theirs
    settlement = ledger_service.ensure_system_account(SETTLEMENT)
    settlement_direction = "debit" if customer_direction == "credit" else "credit"
    try:
        txn = ledger_service.post_transaction(
            txn_type,
            [
                Entry(settlement.id, settlement_direction, amount),
                Entry(account.id, customer_direction, amount),
            ],
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return next(entry for entry in txn.entries if entry.account_id == account_id)


def deposit(owner_id: uuid.UUID, account_id: uuid.UUID, amount: int) -> LedgerEntry:
    return _post("deposit", owner_id, account_id, "credit", amount)


def withdraw(owner_id: uuid.UUID, account_id: uuid.UUID, amount: int) -> LedgerEntry:
    return _post("withdrawal", owner_id, account_id, "debit", amount)