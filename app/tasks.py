import logging

from celery import shared_task

from app.extensions import redis_ext
from app.notifications import build_messages, notifier

logger = logging.getLogger(__name__)

DEDUPE_TTL_SECONDS = 7 * 24 * 3600


@shared_task(
    ignore_result=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def send_transaction_notifications(event_id: int, payload: dict) -> None:
    """Idempotent consumer: the relay may deliver the same event more than once."""
    key = f"notified:{event_id}"
    if redis_ext.client.get(key):
        logger.info("event %s already delivered, skipping", event_id)
        return
    for message in build_messages(payload):
        notifier.send(message)
    redis_ext.client.set(key, "1", ex=DEDUPE_TTL_SECONDS)
