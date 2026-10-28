import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.errors import InsufficientFundsError
from app.extensions import db
from app.models import Account, User
from app.services import ledger_service, money_service

CLEAN = {"balance_mismatches": [], "unbalanced_transactions": []}
LOCK_ROW = "SELECT 1 FROM accounts WHERE id = :id FOR UPDATE"


def make_account(db_session, username):
    user = User(email=f"{username}@example.com", username=username, password_hash="x")
    db_session.add(user)
    db_session.flush()
    account = Account(owner_id=user.id, account_type="savings")
    db_session.add(account)
    db_session.flush()
    return user.id, account.id


def open_account(client, headers):
    response = client.post("/accounts", json={"account_type": "savings"}, headers=headers)
    return response.get_json()["id"]


def deposit(client, headers, account_id, amount):
    return client.post(f"/accounts/{account_id}/deposits", json={"amount": amount}, headers=headers)


def test_concurrent_withdrawals_never_overdraw(db_session, run_concurrently):
    user_id, account_id = make_account(db_session, "alice")
    db_session.commit()
    money_service.deposit(user_id, account_id, 5_000)

    jobs = [lambda: money_service.withdraw(user_id, account_id, 1_000) for _ in range(12)]
    results = run_concurrently(jobs)

    successes = [r for r in results if r[0] == "ok"]
    failures = [r[1] for r in results if r[0] == "error"]
    assert len(successes) == 5
    assert len(failures) == 7
    assert all(isinstance(f, InsufficientFundsError) for f in failures)

    db_session.expire_all()
    assert db_session.get(Account, account_id).balance == 0
    assert ledger_service.reconcile() == CLEAN


def test_opposite_transfers_do_not_deadlock(db_session, run_concurrently):
    alice_id, a_id = make_account(db_session, "alice")
    bob_id, b_id = make_account(db_session, "bob")
    db_session.commit()
    money_service.deposit(alice_id, a_id, 100_000)
    money_service.deposit(bob_id, b_id, 100_000)

    jobs = []
    for _ in range(6):
        jobs.append(lambda: money_service.transfer(alice_id, a_id, b_id, 100))
        jobs.append(lambda: money_service.transfer(bob_id, b_id, a_id, 100))
    results = run_concurrently(jobs)

    assert [r[1] for r in results if r[0] == "error"] == []

    db_session.expire_all()
    assert db_session.get(Account, a_id).balance == 100_000  # 6 out, 6 back
    assert db_session.get(Account, b_id).balance == 100_000
    assert ledger_service.reconcile() == CLEAN


def test_opposite_lock_order_deadlocks_in_postgres(app, db_session):
    """The bug our sorted locking prevents, shown with plain SQL."""
    _, a_id = make_account(db_session, "alice")
    _, b_id = make_account(db_session, "bob")
    db_session.commit()
    barrier = threading.Barrier(2)

    def attempt(first, second):
        with app.app_context():
            try:
                with db.engine.connect() as conn, conn.begin():
                    conn.execute(text(LOCK_ROW), {"id": first})
                    barrier.wait(timeout=10)  # both now hold one lock each
                    conn.execute(text(LOCK_ROW), {"id": second})
                return "ok"
            except OperationalError as exc:
                return exc.orig.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, a_id, b_id), pool.submit(attempt, b_id, a_id)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sorted(outcomes) == ["40P01", "ok"]  # one victim, one survivor


def test_lock_timeout_returns_503_instead_of_hanging(app, client, signup, db_session, monkeypatch):
    alice = signup("alice")
    account_id = open_account(client, alice)
    assert deposit(client, alice, account_id, 1_000).status_code == 201

    monkeypatch.setitem(app.config, "LEDGER_LOCK_TIMEOUT_MS", 300)
    with db.engine.connect() as holder, holder.begin():
        holder.execute(text(LOCK_ROW), {"id": uuid.UUID(account_id)})  # a stuck transaction
        started = time.monotonic()
        response = deposit(client, alice, account_id, 500)
        elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "busy"
    assert elapsed < 3  # failed fast instead of waiting forever
    assert deposit(client, alice, account_id, 500).status_code == 201  # lock gone: works again


def test_hot_account_vs_independent_rows_throughput(db_session, run_concurrently):
    n = 40
    users, sources, dests = [], [], []
    for i in range(n):
        user = User(email=f"u{i}@example.com", username=f"u{i}", password_hash="x")
        db_session.add(user)
        db_session.flush()
        source = Account(owner_id=user.id, account_type="savings")
        dest = Account(owner_id=user.id, account_type="savings")
        db_session.add_all([source, dest])
        db_session.flush()
        users.append(user.id)
        sources.append(source.id)
        dests.append(dest.id)
    db_session.commit()
    for user_id, source_id in zip(users, sources):
        money_service.deposit(user_id, source_id, 10_000)

    def timed(jobs):
        started = time.perf_counter()
        results = run_concurrently(jobs, workers=8)
        assert [r for r in results if r[0] == "error"] == []
        return time.perf_counter() - started

    hot = timed([lambda u=u, s=s: money_service.deposit(u, s, 100) for u, s in zip(users, sources)])
    independent = timed(
        [
            lambda u=u, s=s, d=d: money_service.transfer(u, s, d, 100)
            for u, s, d in zip(users, sources, dests)
        ]
    )
    print(
        f"\n{n} deposits (all lock SETTLEMENT): {hot:.2f}s | {n} independent transfers: {independent:.2f}s"
    )

    assert ledger_service.reconcile() == CLEAN
