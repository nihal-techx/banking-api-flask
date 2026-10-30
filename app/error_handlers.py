import logging

from flask import g, jsonify

from app.errors import RateLimitedError

logger = logging.getLogger("app.error_handlers")


def register_rate_limit_handler(app):
    @app.errorhandler(RateLimitedError)
    def handle_rate_limited(err):
        response = jsonify(error={"code": err.code, "message": err.message, "details": []})
        response.status_code = err.status_code
        response.headers["Retry-After"] = str(err.retry_after)
        return response


def register_unexpected_error_handler(app):
    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        # The traceback goes to the logs. The client gets a generic message plus the
        # request id, so internals (queries, paths, versions) never leak.
        logger.exception("unhandled exception", extra={"error_type": type(err).__name__})
        response = jsonify(
            error={
                "code": "internal_error",
                "message": "Internal server error",
                "details": [],
                "request_id": g.get("request_id"),
            }
        )
        response.status_code = 500
        return response
