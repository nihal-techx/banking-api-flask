import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_AMOUNT = 1_000_000_000  # paise, i.e. 1 crore rupees per operation


class AmountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(strict=True, gt=0, le=MAX_AMOUNT, description="Integer paise")


class TransactionOut(BaseModel):
    transaction_id: uuid.UUID
    type: str
    account_id: uuid.UUID
    amount: int
    balance_after: int
    created_at: datetime