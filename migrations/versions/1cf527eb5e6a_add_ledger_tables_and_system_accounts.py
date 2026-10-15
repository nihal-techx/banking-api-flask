"""add ledger tables and system accounts

Revision ID: 1cf527eb5e6a
Revises: 08507ed998f2
"""
from alembic import op
import sqlalchemy as sa

revision = "1cf527eb5e6a"
down_revision = "08507ed998f2"
branch_labels = None
depends_on = None


def upgrade():
    # accounts: allow system accounts (no owner, identified by system_code)
    op.add_column("accounts", sa.Column("system_code", sa.String(length=50), nullable=True))
    op.alter_column("accounts", "owner_id", existing_type=sa.Uuid(), nullable=True)
    op.create_unique_constraint("uq_accounts_system_code", "accounts", ["system_code"])

    # CHECK constraints are invisible to autogenerate, so they are hand-written.
    op.drop_constraint("ck_accounts_type_valid", "accounts", type_="check")
    op.drop_constraint("ck_accounts_balance_non_negative", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type_valid",
        "accounts",
        "account_type IN ('savings', 'current', 'system')",
    )
    op.create_check_constraint(
        "ck_accounts_balance_non_negative",
        "accounts",
        "account_type = 'system' OR balance >= 0",
    )
    op.create_check_constraint(
        "ck_accounts_owner_matches_type",
        "accounts",
        "(account_type = 'system' AND owner_id IS NULL AND system_code IS NOT NULL) "
        "OR (account_type <> 'system' AND owner_id IS NOT NULL AND system_code IS NULL)",
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('deposit', 'withdrawal', 'transfer')",
            name="ck_transactions_type_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=6), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')", name="ck_ledger_entries_direction_valid"
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ledger_entries_account_id_id", "ledger_entries", ["account_id", "id"]
    )
    op.create_index(
        "ix_ledger_entries_transaction_id", "ledger_entries", ["transaction_id"]
    )


def downgrade():
    # Drop the new CHECKs FIRST: dropping system_code later would silently
    # drop any CHECK that references it, and a later explicit drop would then fail.
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS ck_accounts_owner_matches_type")
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS ck_accounts_balance_non_negative")
    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS ck_accounts_type_valid")

    op.drop_index("ix_ledger_entries_transaction_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account_id_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("transactions")

    # System accounts have no owner and cannot exist in the old schema.
    op.execute("DELETE FROM accounts WHERE account_type = 'system'")
    op.drop_constraint("uq_accounts_system_code", "accounts", type_="unique")
    op.alter_column("accounts", "owner_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("accounts", "system_code")

    op.create_check_constraint(
        "ck_accounts_type_valid", "accounts", "account_type IN ('savings', 'current')"
    )
    op.create_check_constraint(
        "ck_accounts_balance_non_negative", "accounts", "balance >= 0"
    )