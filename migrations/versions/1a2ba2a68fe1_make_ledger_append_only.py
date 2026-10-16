"""make ledger append-only

Revision ID: 1a2ba2a68fe1
Revises: f2e583964a7d
Create Date: 2026-10-16 23:48:51.048387

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a2ba2a68fe1'
down_revision = 'f2e583964a7d'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE FUNCTION forbid_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING
                MESSAGE = 'ledger is append-only (' || TG_OP || ' on ' || TG_TABLE_NAME || ')',
                ERRCODE = '23000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("ledger_entries", "transactions"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation()
            """
        )


def downgrade():
    for table in ("transactions", "ledger_entries"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION forbid_ledger_mutation()")