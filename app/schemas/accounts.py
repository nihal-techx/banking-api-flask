import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CreateAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_type: Literal["savings", "current"]


class AccountPath(BaseModel):
    account_id: uuid.UUID


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_type: str
    balance: int  # integer minor units (paise)
    currency: str
    created_at: datetime


class AccountListOut(BaseModel):
    items: list[AccountOut]