import uuid

from flask import current_app, request
from flask_jwt_extended import get_jwt_identity

from app.errors import IdempotencyKeyError
from app.services import idempotency_service

HEADER = "Idempotency-Key"


def run_idempotent(operation, payload: dict):
    """operation(commit: bool) -> dict. Returns a Flask (body, status[, headers]) tuple."""
    key = request.headers.get(HEADER)

    if key is None:
        if current_app.config["IDEMPOTENCY_KEY_REQUIRED"]:
            raise IdempotencyKeyError(f"The {HEADER} header is required")
        return operation(True), 201

    if not key or len(key) > 255 or not key.isprintable():
        raise IdempotencyKeyError(f"{HEADER} must be 1-255 printable characters")

    request_hash = idempotency_service.fingerprint(request.method, request.path, payload)
    outcome = idempotency_service.run(
        uuid.UUID(get_jwt_identity()),
        key,
        request_hash,
        lambda: operation(False),
    )
    headers = {"Idempotent-Replayed": "true"} if outcome.replayed else {}
    return outcome.body, outcome.status, headers