import logging
import time

import click

from app.extensions import db
from app.services import outbox_service

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
