from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.extensions import db
from app.models import Account, User
from app.services import ledger_service
from app.services.ledger_service import Entry

ROOT = Path(__file__).resolve().parent.parent
GRANTS = ROOT / "db" / "grants.sql"
ROLES = ROOT / "db" / "roles.sql"
CLEAN = {"balance_mismatches": [], "unbalanced_transactions": []}

# Roles are cluster-wide and the test database shares a cluster with the dev database,
# so the tests use their own role. They must never touch the real runtime role.
ROLE = "bank_app_test"

READ_ONLY = {"SELECT": False, "INSERT": False, "UPDATE": False, "DELETE": False, "TRUNCATE": False}
APPEND_ONLY = {**READ_ONLY, "SELECT": True, "INSERT": True}
EXPECTED = {
    "users": APPEND_ONLY,
    "accounts": {**APPEND_ONLY, "UPDATE": True},
    "transactions": APPEND_ONLY,
    "ledger_entries": APPEND_ONLY,
    "idempotency_keys": {**APPEND_ONLY, "UPDATE": True, "DELETE": True},
    "outbox_events": {**APPEND_ONLY, "UPDATE": True, "DELETE": True},
    "alembic_version": READ_ONLY,  # only the migration role may touch it
}


def statements(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


@pytest.fixture
def least_privilege(app):
    """Create a throwaway runtime role and apply the real grants script to it."""
    with app.app_context(), db.engine.begin() as conn:
        conn.execute(
            text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') "
                f"THEN CREATE ROLE {ROLE} NOLOGIN; END IF; END $$"
            )
        )
        for statement in statements(GRANTS.read_text().replace("bank_app", ROLE)):
            conn.execute(text(statement))


def test_roles_script_creates_a_login_role_with_a_password():
    sql = ROLES.read_text()
    assert "CREATE ROLE bank_app" in sql
    assert "PASSWORD" in sql


def test_every_table_needs_an_explicit_grants_decision(app):
    with app.app_context():
        tables = set(db.metadata.tables) | {"alembic_version"}
    assert tables == set(EXPECTED), "new table: decide its privileges in db/grants.sql"


def test_runtime_role_privilege_matrix(app, least_privilege):
    with app.app_context(), db.engine.connect() as conn:
        actual = {
            table: {
                privilege: conn.scalar(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": ROLE, "table": table, "privilege": privilege},
                )
                for privilege in privileges
            }
            for table, privileges in EXPECTED.items()
        }
    assert actual == EXPECTED


def test_runtime_role_can_use_the_id_sequences(app, least_privilege):
    with app.app_context(), db.engine.connect() as conn:
        for sequence in ("ledger_entries_id_seq", "outbox_events_id_seq"):
            allowed = conn.scalar(
                text("SELECT has_sequence_privilege(:role, :name, 'USAGE')"),
                {"role": ROLE, "name": sequence},
            )
            assert allowed, sequence


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_entries SET amount = amount",
        "DELETE FROM ledger_entries",
        "TRUNCATE ledger_entries",
        "UPDATE transactions SET type = type",
        "DELETE FROM users",
    ],
)
def test_runtime_role_is_refused_by_the_database(app, least_privilege, statement):
    with app.app_context():
        conn = db.engine.connect()
        try:
            transaction = conn.begin()
            conn.execute(text(f"SET LOCAL ROLE {ROLE}"))
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text(statement))
            transaction.rollback()
        finally:
            conn.close()


def test_posting_engine_works_with_only_the_granted_privileges(db_session, least_privilege):
    user = User(email="a@example.com", username="alice", password_hash="x")
    db_session.add(user)
    db_session.flush()
    account = Account(owner_id=user.id, account_type="savings")
    db_session.add(account)
    db_session.flush()

    db_session.execute(text(f"SET LOCAL ROLE {ROLE}"))  # from here on: the restricted role
    settlement = ledger_service.ensure_system_account("SETTLEMENT")
    ledger_service.post_transaction(
        "deposit", [Entry(settlement.id, "debit", 100), Entry(account.id, "credit", 100)]
    )
    db_session.flush()

    assert ledger_service.reconcile() == CLEAN
    db_session.rollback()
