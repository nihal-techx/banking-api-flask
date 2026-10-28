import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StatementQuery(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=200)


class TransactionPath(BaseModel):
    transaction_id: uuid.UUID


class StatementItem(BaseModel):
    transaction_id: uuid.UUID
    type: str
    direction: str
    amount: int
    balance_after: int
    counterparty_account_id: uuid.UUID | None
    created_at: datetime


class StatementOut(BaseModel):
    items: list[StatementItem]
    next_cursor: str | None


class TransactionDetailOut(BaseModel):
    transaction_id: uuid.UUID
    type: str
    created_at: datetime
    entries: list[StatementItem]
