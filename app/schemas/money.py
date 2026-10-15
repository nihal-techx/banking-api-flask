import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_AMOUNT = 1_000_000_000  # paise, i.e. 1 crore rupees per operation


class AmountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(strict=True, gt=0, le=MAX_AMOUNT, description="Integer paise")


class TransferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: int = Field(strict=True, gt=0, le=MAX_AMOUNT, description="Integer paise")

    @model_validator(mode="after")
    def accounts_must_differ(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("Cannot transfer to the same account")
        return self


class TransactionOut(BaseModel):
    transaction_id: uuid.UUID
    type: str
    account_id: uuid.UUID
    amount: int
    balance_after: int
    created_at: datetime


class TransferOut(BaseModel):
    transaction_id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: int
    balance_after: int  # the sender's balance after the transfer
    created_at: datetime