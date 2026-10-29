import logging

from flask import g, jsonify

logger = logging.getLogger("app.error_handlers")


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
