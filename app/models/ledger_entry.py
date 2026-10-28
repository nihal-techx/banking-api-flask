import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('debit', 'credit')", name="ck_ledger_entries_direction_valid"
        ),
        CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        Index("ix_ledger_entries_account_id_id", "account_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[int] = mapped_column(BigInteger)  # integer minor units (paise)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(back_populates="entries")
