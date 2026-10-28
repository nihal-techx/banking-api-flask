import base64
import json
import uuid

from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from app.errors import InvalidCursorError, NotFoundError
from app.extensions import db
from app.models import Account, LedgerEntry, Transaction
from app.services import account_service


def encode_cursor(entry_id: int) -> str:
    raw = json.dumps({"id": entry_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        entry_id = json.loads(base64.urlsafe_b64decode(padded))["id"]
    except (ValueError, KeyError, TypeError):
        raise InvalidCursorError("Invalid cursor") from None
    if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
        raise InvalidCursorError("Invalid cursor") from None
    return entry_id


def _entry_view():
    """Entries joined with their transaction type and counterparty account, in ONE query.
    The counterparty is the other entry of the same transaction, ignoring system accounts.
    Assumes two-entry transactions (true for deposit, withdrawal and transfer)."""
    other = aliased(LedgerEntry)
    counterparty = aliased(Account)
    return (
        select(LedgerEntry, Transaction.type, counterparty.id)
        .select_from(LedgerEntry)
        .join(Transaction, Transaction.id == LedgerEntry.transaction_id)
        .outerjoin(
            other,
            and_(
                other.transaction_id == LedgerEntry.transaction_id,
                other.account_id != LedgerEntry.account_id,
            ),
        )
        .outerjoin(
            counterparty,
            and_(counterparty.id == other.account_id, counterparty.account_type != "system"),
        )
    )


def get_statement(owner_id: uuid.UUID, account_id: uuid.UUID, limit: int, cursor: str | None):
    """Newest-first page of an account's ledger entries (keyset pagination)."""
    account = account_service.get_owned_account(owner_id, account_id)  # 404 if not theirs
    stmt = _entry_view().where(LedgerEntry.account_id == account.id)
    if cursor is not None:
        stmt = stmt.where(LedgerEntry.id < decode_cursor(cursor))
    rows = db.session.execute(stmt.order_by(LedgerEntry.id.desc()).limit(limit + 1)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1][0].id) if has_more else None
    return rows, next_cursor


def get_transaction(owner_id: uuid.UUID, transaction_id: uuid.UUID):
    """The caller's own entries of a transaction. 404 if they took no part in it."""
    rows = db.session.execute(
        _entry_view()
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(LedgerEntry.transaction_id == transaction_id, Account.owner_id == owner_id)
        .order_by(LedgerEntry.id)
    ).all()
    if not rows:
        raise NotFoundError("Transaction not found")
    return rows
