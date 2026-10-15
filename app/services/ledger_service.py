from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.extensions import db
from app.models import Account

SETTLEMENT = "SETTLEMENT"


def ensure_system_account(code: str) -> Account:
    """Get-or-create a system account. Race-safe: the unique constraint on
    system_code decides, and ON CONFLICT DO NOTHING makes the loser a no-op.
    Does not commit; the caller owns the transaction."""
    db.session.execute(
        insert(Account)
        .values(account_type="system", system_code=code)
        .on_conflict_do_nothing(index_elements=["system_code"])
    )
    return db.session.scalar(select(Account).where(Account.system_code == code))