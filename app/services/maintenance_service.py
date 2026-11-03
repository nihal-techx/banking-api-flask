from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, select

from app.extensions import db
from app.models import IdempotencyKey, OutboxEvent


def _cutoff(older_than: timedelta) -> datetime:
    return datetime.now(UTC) - older_than


def _expired_keys(older_than: timedelta):
    return IdempotencyKey.created_at < _cutoff(older_than)


def _purgeable_events(older_than: timedelta):
    # Only events that were already published. An unpublished event is a notification that
    # has not gone out yet, so it is never deleted, however old it is.
    return and_(
        OutboxEvent.published_at.is_not(None),
        OutboxEvent.published_at < _cutoff(older_than),
    )


def _delete_in_batches(model, condition, batch_size: int) -> int:
    """Short transactions: delete a batch, commit, repeat until a batch comes back short.
    SKIP LOCKED lets two purgers run side by side without blocking each other."""
    total = 0
    while True:
        batch = (
            select(model.id).where(condition).limit(batch_size).with_for_update(skip_locked=True)
        )
        result = db.session.execute(
            delete(model).where(model.id.in_(batch)).execution_options(synchronize_session=False)
        )
        db.session.commit()
        total += result.rowcount
        if result.rowcount < batch_size:
            return total


def purge_idempotency_keys(older_than: timedelta, batch_size: int) -> int:
    return _delete_in_batches(IdempotencyKey, _expired_keys(older_than), batch_size)


def purge_outbox_events(older_than: timedelta, batch_size: int) -> int:
    return _delete_in_batches(OutboxEvent, _purgeable_events(older_than), batch_size)


def count_expired_idempotency_keys(older_than: timedelta) -> int:
    stmt = select(func.count()).select_from(IdempotencyKey).where(_expired_keys(older_than))
    return db.session.scalar(stmt)


def count_purgeable_outbox_events(older_than: timedelta) -> int:
    stmt = select(func.count()).select_from(OutboxEvent).where(_purgeable_events(older_than))
    return db.session.scalar(stmt)
