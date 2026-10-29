import json
import logging
import sys
from datetime import UTC, datetime

from flask import g, has_request_context

_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_NO_REQUEST = "-"
_factory_installed = False


class JsonFormatter(logging.Formatter):
    """One JSON object per record. Extra fields passed via `extra=` become top-level keys."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", _NO_REQUEST)
        if request_id != _NO_REQUEST:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key != "request_id":
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _install_record_factory():
    """Stamp every log record with the current request id, from any logger."""
    global _factory_installed
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        in_request = has_request_context()
        record.request_id = (g.get("request_id") if in_request else None) or _NO_REQUEST
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging(app):
    _install_record_factory()
    if app.config.get("TESTING"):
        return  # pytest captures logs itself
    handler = logging.StreamHandler(sys.stdout)
    if app.config["LOG_FORMAT"] == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s",
                defaults={"request_id": _NO_REQUEST},
            )
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(app.config["LOG_LEVEL"].upper())
