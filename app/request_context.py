import logging
import re
import time
import uuid

from flask import g, request

logger = logging.getLogger("app.request")

# Strict on purpose: an unchecked client value in logs is a log-injection risk.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = {"/health", "/ready"}  # probes hit these every few seconds


def register_request_hooks(app):
    @app.before_request
    def start_request():
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied if _VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        started = g.get("request_started")
        if started is not None:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            level = logging.DEBUG if request.path in _QUIET_PATHS else logging.INFO
            logger.log(
                level,
                "%s %s %s %.1fms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                # path only, never the query string, headers or body
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response
