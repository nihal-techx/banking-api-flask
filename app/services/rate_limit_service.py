import hashlib
import logging

from flask import current_app, request
from redis.exceptions import RedisError

from app.errors import RateLimitedError
from app.extensions import redis_ext

logger = logging.getLogger(__name__)


def client_ip() -> str:
    """The caller's IP address.

    X-Forwarded-For is client-controlled, so it is trusted only for the entries appended
    by OUR proxies. With N trusted proxies the client is the Nth entry from the right.
    With none configured the header is ignored entirely."""
    trusted = int(current_app.config["TRUSTED_PROXY_COUNT"])
    if trusted > 0:
        hops = [
            hop.strip()
            for hop in request.headers.get("X-Forwarded-For", "").split(",")
            if hop.strip()
        ]
        if len(hops) >= trusted:
            return hops[-trusted]
    return request.remote_addr or "unknown"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]  # no raw emails or IPs in Redis keys


def enforce(scope: str, identity: str, limit: int, window_seconds: int) -> None:
    """Fixed-window counter in Redis. Raises RateLimitedError once `limit` is exceeded.

    INCR, EXPIRE NX and TTL run in one MULTI/EXEC transaction, so the window starts on the
    first hit and can never be left without an expiry. Fails open if Redis is unavailable."""
    if not current_app.config["RATE_LIMIT_ENABLED"]:
        return
    key = f"ratelimit:{scope}:{_digest(identity)}"
    try:
        pipe = redis_ext.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
    except RedisError:
        logger.warning("rate limiter unavailable, allowing the request", extra={"scope": scope})
        return
    if count > limit:
        raise RateLimitedError(retry_after=max(int(ttl), 1))


def check_login(email: str) -> None:
    cfg = current_app.config
    ip = client_ip()
    window = cfg["RATE_LIMIT_WINDOW_SECONDS"]
    enforce("login:ip", ip, cfg["RATE_LIMIT_LOGIN_IP_ATTEMPTS"], window)
    enforce("login:identity", f"{ip}|{email}", cfg["RATE_LIMIT_LOGIN_ATTEMPTS"], window)


def check_register() -> None:
    cfg = current_app.config
    enforce(
        "register:ip",
        client_ip(),
        cfg["RATE_LIMIT_REGISTER_IP_ATTEMPTS"],
        cfg["RATE_LIMIT_WINDOW_SECONDS"],
    )
