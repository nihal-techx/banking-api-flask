import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_AMOUNT = 1_000_000_000  # paise, i.e. 1 crore rupees per operation

AMOUNT_DESCRIPTION = "Amount in paise (1 rupee = 100 paise). 10000 is INR 100.00."


class IdempotencyHeader(BaseModel):
    idempotency_key: str | None = Field(
        default=None,
        alias="Idempotency-Key",
        description=(
            "Unique key (up to 255 characters, e.g. a UUID) that makes retries safe. "
            "Retrying with the same key returns the original response."
        ),
    )


class AmountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(
        strict=True, gt=0, le=MAX_AMOUNT, description=AMOUNT_DESCRIPTION, examples=[10000]
    )


class TransferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_account_id: uuid.UUID = Field(description="One of your own accounts.")
    to_account_id: uuid.UUID = Field(description="Any customer account.")
    amount: int = Field(
        strict=True, gt=0, le=MAX_AMOUNT, description=AMOUNT_DESCRIPTION, examples=[2500]
    )

    @model_validator(mode="after")
    def accounts_must_differ(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("Cannot transfer to the same account")
        return self


class TransactionOut(BaseModel):
    transaction_id: uuid.UUID
    type: str = Field(description="deposit, withdrawal or transfer.")
    account_id: uuid.UUID
    amount: int = Field(description=AMOUNT_DESCRIPTION)
    balance_after: int = Field(description="Balance of this account right after the transaction, in paise.")
    created_at: datetime


class TransferOut(BaseModel):
    transaction_id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: int = Field(description=AMOUNT_DESCRIPTION)
    balance_after: int = Field(description="The sender's balance right after the transfer, in paise.")
    created_at: datetime