import time

from flask import current_app

from app.extensions import redis_ext


def refresh_ttl_seconds() -> int:
    return int(current_app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds())


def _remaining(exp: int) -> int:
    return max(int(exp - time.time()), 1)


def consume_token(jti: str, exp: int) -> bool:
    """Atomically mark a token as used. True only for the first caller."""
    return bool(redis_ext.client.set(f"revoked:jti:{jti}", "1", nx=True, ex=_remaining(exp)))


def revoke_family(fid: str) -> None:
    redis_ext.client.set(f"revoked:fid:{fid}", "1", ex=refresh_ttl_seconds())


def is_revoked(payload: dict) -> bool:
    keys = [f"revoked:jti:{payload['jti']}"]
    if payload.get("fid"):
        keys.append(f"revoked:fid:{payload['fid']}")
    return any(value is not None for value in redis_ext.client.mget(keys))
