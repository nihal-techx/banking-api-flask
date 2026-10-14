from flask import jsonify
from werkzeug.exceptions import HTTPException


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


def _error_response(status, code, message, details=None):
    response = jsonify(error={"code": code, "message": message, "details": details or []})
    response.status_code = status
    return response


def validation_error_response(exc):
    """Called by flask-openapi3 with a pydantic ValidationError."""
    details = [
        {"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]}
        for err in exc.errors(include_url=False, include_context=False, include_input=False)
    ]
    return _error_response(422, "validation_error", "Invalid request", details)


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err):
        return _error_response(err.status_code, err.code, err.message, err.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        code = err.name.lower().replace(" ", "_")
        return _error_response(err.code, code, err.description)