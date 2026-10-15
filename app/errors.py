import redis
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


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class InsufficientFundsError(AppError):
    status_code = 422
    code = "insufficient_funds"


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

    @app.errorhandler(redis.RedisError)
    def handle_redis_error(err):
        return _error_response(
            503, "service_unavailable", "Service temporarily unavailable"
        )


def register_jwt_error_handlers(jwt):
    @jwt.unauthorized_loader
    def missing_token(reason):
        return _error_response(401, "missing_token", "Authentication required")

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return _error_response(401, "invalid_token", "Invalid token")

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return _error_response(401, "token_expired", "Token has expired")


def register_jwt_revocation(jwt):
    from app.services import token_service

    @jwt.token_in_blocklist_loader
    def is_revoked(jwt_header, jwt_payload):
        return token_service.is_revoked(jwt_payload)

    @jwt.revoked_token_loader
    def revoked(jwt_header, jwt_payload):
        # A revoked *refresh* token being presented means it was reused.
        if jwt_payload.get("type") == "refresh" and jwt_payload.get("fid"):
            token_service.revoke_family(jwt_payload["fid"])
        return _error_response(401, "token_revoked", "Token has been revoked")
