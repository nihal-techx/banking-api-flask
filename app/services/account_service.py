import uuid

from sqlalchemy import select

from app.errors import NotFoundError
from app.extensions import db
from app.models import Account


def open_account(owner_id: uuid.UUID, account_type: str) -> Account:
    account = Account(owner_id=owner_id, account_type=account_type)
    db.session.add(account)
    db.session.commit()
    return account


def list_accounts(owner_id: uuid.UUID) -> list[Account]:
    stmt = select(Account).where(Account.owner_id == owner_id).order_by(Account.created_at)
    return list(db.session.scalars(stmt))


def get_owned_account(owner_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    stmt = select(Account).where(Account.id == account_id, Account.owner_id == owner_id)
    account = db.session.scalar(stmt)
    if account is None:
        raise NotFoundError("Account not found")
    return account