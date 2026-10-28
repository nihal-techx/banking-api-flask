import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Account(db.Model):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('savings', 'current', 'system')",
            name="ck_accounts_type_valid",
        ),
        CheckConstraint(
            "account_type = 'system' OR balance >= 0",
            name="ck_accounts_balance_non_negative",
        ),
        CheckConstraint(
            "(account_type = 'system' AND owner_id IS NULL AND system_code IS NOT NULL) "
            "OR (account_type <> 'system' AND owner_id IS NOT NULL AND system_code IS NULL)",
            name="ck_accounts_owner_matches_type",
        ),
        UniqueConstraint("system_code", name="uq_accounts_system_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(20))
    system_code: Mapped[str | None] = mapped_column(String(50))
    balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[Optional["User"]] = relationship(back_populates="accounts")
