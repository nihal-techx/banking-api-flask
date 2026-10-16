from pathlib import Path

import pytest
from flask_migrate import check, downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db

MIGRATIONS = str(Path(__file__).resolve().parent.parent / "migrations")
TABLES = {"users", "accounts", "transactions", "ledger_entries", "idempotency_keys", "outbox_events"}


def test_models_and_migrations_agree(app):
    """Fails if a model changed without a migration. (Alembic cannot see CHECK constraints.)"""
    with app.app_context():
        try:
            check(directory=MIGRATIONS)
        except SystemExit:
            pytest.fail("models and migrations have drifted: run `flask db migrate`")


def test_migrations_round_trip(app):
    with app.app_context():
        try:
            downgrade(directory=MIGRATIONS, revision="base")
            assert set(inspect(db.engine).get_table_names()) <= {"alembic_version"}
            with db.engine.connect() as conn:
                leftover = conn.scalar(
                    text("SELECT count(*) FROM pg_proc WHERE proname = 'forbid_ledger_mutation'")
                )
            assert leftover == 0  # the downgrade cleaned up the trigger function too
        finally:
            upgrade(directory=MIGRATIONS)  # always leave the shared test DB at head

    with app.app_context():
        assert TABLES <= set(inspect(db.engine).get_table_names())