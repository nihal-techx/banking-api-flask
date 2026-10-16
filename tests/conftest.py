from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import text

from app import create_app
from app.config import TestingConfig
from app.extensions import db, redis_ext

MIGRATIONS = str(Path(__file__).resolve().parent.parent / "migrations")


def _reset_schema():
    """Destructive. Refuses to touch anything that is not obviously a test database."""
    database = db.engine.url.database or ""
    if not database.endswith("_test"):
        raise RuntimeError(f"refusing to reset non-test database {database!r}")
    with db.engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def app():
    app = create_app(TestingConfig)
    with app.app_context():
        _reset_schema()
        upgrade(directory=MIGRATIONS)  # the schema comes from the migrations, as in production
    yield app


@pytest.fixture(autouse=True)
def clean_db(app):
    yield
    with app.app_context():
        tables = ", ".join(table.name for table in db.metadata.sorted_tables)
        # TRUNCATE (unlike DELETE) does not fire the append-only row triggers. The
        # lock_timeout turns a leaked open transaction into a loud failure, not a hang.
        db.session.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()
    redis_ext.client.flushdb()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def signup(client):
    """Register + log in a user; returns ready-to-use auth headers."""

    def _signup(username):
        creds = {
            "email": f"{username}@example.com",
            "username": username,
            "password": "s3cret-pass-1",
        }
        assert client.post("/auth/register", json=creds).status_code == 201
        login = client.post(
            "/auth/login", json={"email": creds["email"], "password": creds["password"]}
        )
        return {"Authorization": f"Bearer {login.get_json()['access_token']}"}

    return _signup


class Bank:
    """Thin helpers over the HTTP API so tests read as scenarios, not plumbing."""

    def __init__(self, client):
        self.client = client

    def _post(self, url, headers, body, key=None):
        merged = dict(headers)
        if key is not None:
            merged["Idempotency-Key"] = key
        return self.client.post(url, json=body, headers=merged)

    def open_account(self, headers, account_type="savings"):
        response = self.client.post(
            "/accounts", json={"account_type": account_type}, headers=headers
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()["id"]

    def deposit(self, headers, account_id, amount, key=None):
        return self._post(f"/accounts/{account_id}/deposits", headers, {"amount": amount}, key)

    def withdraw(self, headers, account_id, amount, key=None):
        return self._post(f"/accounts/{account_id}/withdrawals", headers, {"amount": amount}, key)

    def transfer(self, headers, from_id, to_id, amount, key=None):
        body = {"from_account_id": from_id, "to_account_id": to_id, "amount": amount}
        return self._post("/transfers", headers, body, key)

    def fund(self, headers, account_id, amount):
        response = self.deposit(headers, account_id, amount)
        assert response.status_code == 201, response.get_json()
        return response.get_json()

    def balance(self, headers, account_id):
        response = self.client.get(f"/accounts/{account_id}", headers=headers)
        return response.get_json()["balance"]


@pytest.fixture
def bank(client):
    return Bank(client)


@pytest.fixture
def run_concurrently(app):
    """Run callables in parallel threads, each with its own app context (own DB session).
    workers=None releases all jobs at once through a barrier, to maximize overlap.
    Returns a list of ("ok", result) or ("error", exception)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    def _run(jobs, workers=None):
        barrier = threading.Barrier(len(jobs)) if workers is None else None

        def wrap(job):
            def runner():
                with app.app_context():
                    if barrier is not None:
                        barrier.wait(timeout=10)
                    try:
                        return ("ok", job())
                    except Exception as exc:
                        return ("error", exc)

            return runner

        with ThreadPoolExecutor(max_workers=workers or len(jobs)) as pool:
            futures = [pool.submit(wrap(job)) for job in jobs]
            return [future.result(timeout=60) for future in futures]

    return _run