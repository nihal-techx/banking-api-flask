import logging
import time
from datetime import timedelta

import click

from app.extensions import db
from app.services import maintenance_service, outbox_service

logger = logging.getLogger(__name__)


def register_cli(app):
    @app.cli.command("outbox-relay")
    @click.option("--once", is_flag=True, help="Process one batch and exit.")
    @click.option(
        "--interval",
        default=1.0,
        show_default=True,
        help="Seconds to sleep when idle, and the first retry delay after a failure.",
    )
    @click.option(
        "--max-backoff",
        default=30.0,
        show_default=True,
        help="Upper bound for the retry delay after repeated failures.",
    )
    def outbox_relay(once, interval, max_backoff):
        """Publish pending outbox events to the message broker."""
        failures = 0
        while True:
            try:
                count = outbox_service.publish_pending()
            except Exception as exc:
                db.session.rollback()
                if once:
                    raise
                failures += 1
                delay = min(max_backoff, interval * 2 ** (failures - 1))
                logger.warning(
                    "outbox relay failed (%s: %s); retrying in %.1fs",
                    type(exc).__name__,
                    exc,
                    delay,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                time.sleep(delay)
                continue
            failures = 0
            if count:
                click.echo(f"published {count} event(s)")
            if once:
                return
            if count == 0:
                time.sleep(interval)

    @app.cli.command("purge")
    @click.option(
        "--dry-run", is_flag=True, help="Report what would be deleted without deleting anything."
    )
    def purge(dry_run):
        """Delete expired idempotency keys and old, already-published outbox events."""
        key_age = timedelta(hours=app.config["IDEMPOTENCY_KEY_RETENTION_HOURS"])
        event_age = timedelta(days=app.config["OUTBOX_RETENTION_DAYS"])
        batch_size = app.config["PURGE_BATCH_SIZE"]
        if dry_run:
            keys = maintenance_service.count_expired_idempotency_keys(key_age)
            events = maintenance_service.count_purgeable_outbox_events(event_age)
            click.echo(f"would delete {keys} idempotency key(s) and {events} outbox event(s)")
            return
        keys = maintenance_service.purge_idempotency_keys(key_age, batch_size)
        events = maintenance_service.purge_outbox_events(event_age, batch_size)
        logger.info("purge complete", extra={"idempotency_keys": keys, "outbox_events": events})
        click.echo(f"deleted {keys} idempotency key(s) and {events} outbox event(s)")
