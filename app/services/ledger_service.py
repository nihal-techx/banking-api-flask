import uuid
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError

from app.errors import InsufficientFundsError, ServiceBusyError
from app.extensions import db
from app.models import Account, LedgerEntry, OutboxEvent, Transaction

SETTLEMENT = "SETTLEMENT"

_LOCK_NOT_AVAILABLE = "55P03"  # lock_timeout expired
_DEADLOCK_DETECTED = "40P01"


class LedgerError(Exception):
    """A posting that violates ledger invariants. Always a bug in the caller."""


@dataclass(frozen=True)
class Entry:
    account_id: uuid.UUID
    direction: str  # "debit" or "credit"
    amount: int  # positive integer, minor units (paise)


def ensure_system_account(code: str) -> Account:
    """Get-or-create a system account. Race-safe: the unique constraint on
    system_code decides, and ON CONFLICT DO NOTHING makes the loser a no-op.
    Does not commit; the caller owns the transaction."""
    account = db.session.scalar(select(Account).where(Account.system_code == code))
    if account is not None:
        return account
    db.session.execute(
        insert(Account)
        .values(account_type="system", system_code=code)
        .on_conflict_do_nothing(index_elements=["system_code"])
    )
    return db.session.scalar(select(Account).where(Account.system_code == code))


def _validate(entries: list[Entry]) -> None:
    if len(entries) < 2:
        raise LedgerError("A transaction needs at least two entries")
    if len({e.account_id for e in entries}) != len(entries):
        raise LedgerError("An account may appear only once per transaction")
    for e in entries:
        if e.direction not in ("debit", "credit"):
            raise LedgerError(f"Invalid direction: {e.direction!r}")
        if not isinstance(e.amount, int) or isinstance(e.amount, bool) or e.amount <= 0:
            raise LedgerError("Amounts must be positive integers")
    debits = sum(e.amount for e in entries if e.direction == "debit")
    credits = sum(e.amount for e in entries if e.direction == "credit")
    if debits != credits:
        raise LedgerError("Debits must equal credits")


def _lock_accounts(ids: list[uuid.UUID]) -> dict[uuid.UUID, Account]:
    """Lock rows in ID order (prevents deadlocks) and fail fast if a lock is
    unavailable (prevents pile-ups behind a stuck transaction)."""
    timeout_ms = int(current_app.config["LEDGER_LOCK_TIMEOUT_MS"])
    # set_config(..., true) is SET LOCAL: it lasts only until this transaction ends.
    db.session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": f"{timeout_ms}ms"},
    )
    try:
        rows = db.session.scalars(
            select(Account)
            .where(Account.id.in_(ids))
            .order_by(Account.id)
            .with_for_update()
            .execution_options(populate_existing=True)  # refresh stale identity-map objects
        ).all()
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) in (_LOCK_NOT_AVAILABLE, _DEADLOCK_DETECTED):
            raise ServiceBusyError("Account is busy, please retry") from exc
        raise
    return {account.id: account for account in rows}


def post_transaction(txn_type: str, entries: list[Entry], description: str | None = None) -> Transaction:
    """Post a balanced set of entries. The ONLY code that writes balances.
    Also writes the outbox event, in the same transaction, so a posting and its
    event exist together or not at all. Never commits: the caller owns the transaction."""
    _validate(entries)

    ids = sorted({e.account_id for e in entries})
    accounts = _lock_accounts(ids)
    if len(accounts) != len(ids):
        raise LedgerError("Posting references an unknown account")
    if len({account.currency for account in accounts.values()}) != 1:
        raise LedgerError("Cross-currency postings are not supported")

    # Phase 1: compute and check everything. Nothing is written yet.
    plan = []
    for e in entries:
        account = accounts[e.account_id]
        delta = e.amount if e.direction == "credit" else -e.amount
        new_balance = account.balance + delta
        if account.account_type != "system" and new_balance < 0:
            raise InsufficientFundsError("Insufficient funds")
        plan.append((account, e, new_balance))

    # Phase 2: write the transaction, its entries and the cached balances.
    txn = Transaction(type=txn_type, description=description)
    db.session.add(txn)
    db.session.flush()
    for account, e, new_balance in plan:
        account.balance = new_balance
        db.session.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=account.id,
                direction=e.direction,
                amount=e.amount,
                balance_after=new_balance,
            )
        )

    # Phase 3: the outbox event, atomic with the money.
    db.session.add(
        OutboxEvent(
            event_type="transaction.posted",
            payload={
                "transaction_id": str(txn.id),
                "type": txn_type,
                "entries": [
                    {
                        "account_id": str(account.id),
                        "owner_id": str(account.owner_id) if account.owner_id else None,
                        "direction": e.direction,
                        "amount": e.amount,
                        "balance_after": new_balance,
                    }
                    for account, e, new_balance in plan
                ],
            },
        )
    )
    return txn


def reconcile() -> dict:
    """Return everything that violates the ledger's invariants (empty lists = healthy)."""
    signed = func.coalesce(
        func.sum(
            case(
                (LedgerEntry.direction == "credit", LedgerEntry.amount),
                else_=-LedgerEntry.amount,
            )
        ),
        0,
    )
    mismatches = db.session.execute(
        select(Account.id, Account.balance, signed.label("ledger_balance"))
        .outerjoin(LedgerEntry, LedgerEntry.account_id == Account.id)
        .group_by(Account.id, Account.balance)
        .having(Account.balance != signed)
    ).all()
    unbalanced = db.session.execute(
        select(LedgerEntry.transaction_id, signed.label("net"))
        .group_by(LedgerEntry.transaction_id)
        .having(signed != 0)
    ).all()
    return {
        "balance_mismatches": [
            {
                "account_id": row.id,
                "cached_balance": row.balance,
                "ledger_balance": int(row.ledger_balance),
            }
            for row in mismatches
        ],
        "unbalanced_transactions": [
            {"transaction_id": row.transaction_id, "net": int(row.net)} for row in unbalanced
        ],
    }