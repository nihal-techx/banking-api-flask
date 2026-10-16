from sqlalchemy import func, select

from app import tasks
from app.extensions import db
from app.models import OutboxEvent


def _publish(event: OutboxEvent) -> None:
    tasks.send_transaction_notifications.apply_async(args=[event.id, event.payload])


def publish_pending(batch_size: int = 100) -> int:
    """Hand pending events to the broker, then mark them published.

    Publish-then-mark is at-least-once: a crash in between means a re-publish, which
    the idempotent consumer absorbs. SKIP LOCKED lets several relays run side by side,
    each taking a different batch. Always commits, which releases the row locks."""
    events = db.session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()

    published = 0
    try:
        for event in events:
            _publish(event)  # raises if the broker is unreachable
            event.published_at = func.now()
            published += 1
    finally:
        db.session.commit()  # keep the marks for events that did go out
    return published