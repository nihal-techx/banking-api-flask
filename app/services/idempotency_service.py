import hashlib
import json
import uuid
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError

from app.errors import IdempotencyKeyReuseError, ServiceBusyError
from app.extensions import db
from app.models import IdempotencyKey

_LOCK_NOT_AVAILABLE = "55P03"


@dataclass(frozen=True)
class Outcome:
    body: dict
    status: int
    replayed: bool


def fingerprint(method: str, path: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method}\n{path}\n{canonical}".encode()).hexdigest()


def _claim(user_id: uuid.UUID, key: str, request_hash: str):
    """Try to insert the claim row. Returns its id, or None if the key already exists.
    If another transaction is inserting the same key right now, Postgres makes this
    statement WAIT until that transaction commits or rolls back."""
    timeout_ms = int(current_app.config["LEDGER_LOCK_TIMEOUT_MS"])
    db.session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": f"{timeout_ms}ms"},
    )
    try:
        return db.session.scalar(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, request_hash=request_hash)
            .on_conflict_do_nothing(index_elements=["user_id", "key"])
            .returning(IdempotencyKey.id)
        )
    except OperationalError as exc:
        db.session.rollback()
        if getattr(exc.orig, "sqlstate", None) == _LOCK_NOT_AVAILABLE:
            raise ServiceBusyError(
                "A request with this key is still being processed, please retry"
            ) from exc
        raise


def _store_response(record_id: uuid.UUID, status: int, body: dict) -> None:
    db.session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == record_id)
        .values(response_status=status, response_body=body)
    )


def run(user_id: uuid.UUID, key: str, request_hash: str, operation, status: int = 201) -> Outcome:
    """Execute operation() at most once per (user, key).

    operation() must do its work WITHOUT committing and return a JSON-serializable dict.
    The claim row, the money movement and the stored response commit as ONE transaction.
    """
    record_id = _claim(user_id, key, request_hash)

    if record_id is None:  # key already used: replay or reject
        existing = db.session.execute(
            select(
                IdempotencyKey.request_hash,
                IdempotencyKey.response_status,
                IdempotencyKey.response_body,
            ).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        ).one()
        db.session.rollback()  # nothing to keep; release the connection
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReuseError(
                "This Idempotency-Key was already used with a different request"
            )
        if existing.response_body is None:  # cannot normally happen; fail safe
            raise ServiceBusyError("A request with this key is still being processed")
        return Outcome(existing.response_body, existing.response_status, replayed=True)

    try:
        body = operation()
        _store_response(record_id, status, body)
        db.session.commit()
    except Exception:
        db.session.rollback()  # discards the claim row too, so the key can be retried
        raise
    return Outcome(body, status, replayed=False)