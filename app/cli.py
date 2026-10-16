import logging
import time

import click

from app.extensions import db
from app.services import outbox_service

logger = logging.getLogger(__name__)


def register_cli(app):
    @app.cli.command("outbox-relay")
    @click.option("--once", is_flag=True, help="Process one batch and exit.")
    @click.option("--interval", default=1.0, show_default=True, help="Seconds to sleep when idle.")
    def outbox_relay(once, interval):
        """Publish pending outbox events to the message broker."""
        while True:
            try:
                count = outbox_service.publish_pending()
            except Exception:
                db.session.rollback()
                logger.exception("outbox relay failed; will retry")
                if once:
                    raise
                count = 0
            if count:
                click.echo(f"published {count} event(s)")
            if once:
                return
            if count == 0:
                time.sleep(interval)