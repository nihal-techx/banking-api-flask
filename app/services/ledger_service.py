import uuid
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from app.errors import InsufficientFundsError
from app.extensions import db
from app.models import Account, LedgerEntry, Transaction

SETTLEMENT = "SETTLEMENT"


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


def post_transaction(txn_type: str, entries: list[Entry], description: str | None = None) -> Transaction:
    """Post a balanced set of entries. The ONLY code that writes balances.
    Never commits: the caller owns the transaction boundary."""
    _validate(entries)

    ids = sorted({e.account_id for e in entries})  # fixed lock order prevents deadlocks
    locked = db.session.scalars(
        select(Account)
        .where(Account.id.in_(ids))
        .order_by(Account.id)
        .with_for_update()
        .execution_options(populate_existing=True)  # refresh stale identity-map objects
    )
    accounts = {account.id: account for account in locked}
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