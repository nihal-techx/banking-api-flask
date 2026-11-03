from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from app.models import IdempotencyKey, OutboxEvent, User
from app.services import maintenance_service

KEY_AGE = timedelta(hours=24)
EVENT_AGE = timedelta(days=7)


def ago(age: timedelta) -> datetime:
    return datetime.now(UTC) - age


def make_user(db_session):
    user = User(email="a@example.com", username="alice", password_hash="x")
    db_session.add(user)
    db_session.flush()
    return user.id


def add_key(db_session, user_id, name, age):
    db_session.add(IdempotencyKey(user_id=user_id, key=name, request_hash="h", created_at=ago(age)))


def add_event(db_session, created, published=None):
    db_session.add(
        OutboxEvent(
            event_type="transaction.posted",
            payload={},
            created_at=ago(created),
            published_at=ago(published) if published else None,
        )
    )


def count(db_session, model):
    return db_session.scalar(select(func.count()).select_from(model))


def seed(db_session):
    user_id = make_user(db_session)
    add_key(db_session, user_id, "old", timedelta(hours=48))
    add_key(db_session, user_id, "old-2", timedelta(hours=30))
    add_key(db_session, user_id, "fresh", timedelta(hours=1))
    add_event(db_session, created=timedelta(days=30), published=timedelta(days=10))
    add_event(db_session, created=timedelta(days=30))  # old but never published
    db_session.commit()


def test_purge_deletes_only_expired_idempotency_keys(db_session):
    user_id = make_user(db_session)
    add_key(db_session, user_id, "old", timedelta(hours=48))
    add_key(db_session, user_id, "just-expired", timedelta(hours=25))
    add_key(db_session, user_id, "fresh", timedelta(hours=1))

    assert maintenance_service.purge_idempotency_keys(KEY_AGE, batch_size=100) == 2
    assert db_session.scalars(select(IdempotencyKey.key)).all() == ["fresh"]


def test_purge_never_touches_unpublished_outbox_events(db_session):
    add_event(db_session, created=timedelta(days=30), published=timedelta(days=10))  # purge
    add_event(db_session, created=timedelta(days=3), published=timedelta(days=1))  # too recent
    add_event(db_session, created=timedelta(days=30))  # old but unpublished: must stay
    add_event(db_session, created=timedelta(minutes=1))  # new and unpublished

    assert maintenance_service.purge_outbox_events(EVENT_AGE, batch_size=100) == 1
    assert count(db_session, OutboxEvent) == 3
    unpublished = (
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
    )
    assert db_session.scalar(unpublished) == 2


def test_purge_works_in_batches_and_is_repeatable(db_session):
    user_id = make_user(db_session)
    for i in range(25):
        add_key(db_session, user_id, f"old-{i}", timedelta(hours=48))

    assert maintenance_service.purge_idempotency_keys(KEY_AGE, batch_size=10) == 25
    assert count(db_session, IdempotencyKey) == 0
    assert maintenance_service.purge_idempotency_keys(KEY_AGE, batch_size=10) == 0


def test_dry_run_reports_without_deleting(app, db_session):
    seed(db_session)

    result = app.test_cli_runner().invoke(args=["purge", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would delete 2 idempotency key(s) and 1 outbox event(s)" in result.output
    assert count(db_session, IdempotencyKey) == 3
    assert count(db_session, OutboxEvent) == 2


def test_purge_command_deletes_and_reports(app, db_session):
    seed(db_session)

    result = app.test_cli_runner().invoke(args=["purge"])

    assert result.exit_code == 0, result.output
    assert "deleted 2 idempotency key(s) and 1 outbox event(s)" in result.output
    assert count(db_session, IdempotencyKey) == 1
    assert count(db_session, OutboxEvent) == 1


def test_an_expired_key_is_treated_as_new_after_the_purge(signup, bank, db_session):
    alice = signup("alice")
    account_id = bank.open_account(alice)
    assert bank.deposit(alice, account_id, 1_000, key="reuse-me").status_code == 201
    replay = bank.deposit(alice, account_id, 1_000, key="reuse-me")
    assert replay.headers["Idempotent-Replayed"] == "true"  # inside the retention window

    db_session.execute(text("UPDATE idempotency_keys SET created_at = now() - interval '48 hours'"))
    db_session.commit()
    maintenance_service.purge_idempotency_keys(KEY_AGE, batch_size=100)

    again = bank.deposit(alice, account_id, 1_000, key="reuse-me")
    assert again.status_code == 201
    assert "Idempotent-Replayed" not in again.headers  # a brand-new request after expiry
    assert bank.balance(alice, account_id) == 2_000
