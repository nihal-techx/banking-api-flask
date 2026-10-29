import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

DEV_SECRET_KEY = "dev-secret-change-me"
DEV_JWT_SECRET_KEY = "dev-only-jwt-secret-change-me-32-bytes-min"
MIN_SECRET_LENGTH = 32

APP_ENV = os.getenv("APP_ENV", "development")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_ENV = APP_ENV
    SECRET_KEY = os.getenv("SECRET_KEY", DEV_SECRET_KEY)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", DEV_JWT_SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    LEDGER_LOCK_TIMEOUT_MS = 3000
    # Required in production, optional elsewhere unless overridden.
    IDEMPOTENCY_KEY_REQUIRED = env_bool("IDEMPOTENCY_KEY_REQUIRED", APP_ENV == "production")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json" if APP_ENV == "production" else "text")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL")
    RABBITMQ_URL = os.getenv("RABBITMQ_URL")
    CELERY = {
        "broker_url": os.getenv("RABBITMQ_URL"),
        "task_ignore_result": True,
        "broker_connection_retry_on_startup": True,
    }


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    IDEMPOTENCY_KEY_REQUIRED = False
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://bank:bank@localhost:5434/banking_test",
    )
    REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6381/1")
    CELERY = {
        "broker_url": "memory://",
        "task_always_eager": True,  # tasks run inline: no broker needed in tests
        "task_eager_propagates": True,
        "task_ignore_result": True,
    }


def validate_production_config(config) -> list[str]:
    """Return everything wrong with a production configuration. Never includes secret values."""
    problems = []
    for name, dev_value in (
        ("SECRET_KEY", DEV_SECRET_KEY),
        ("JWT_SECRET_KEY", DEV_JWT_SECRET_KEY),
    ):
        value = config.get(name) or ""
        if value == dev_value:
            problems.append(f"{name} is still the development default")
        elif len(value) < MIN_SECRET_LENGTH:
            problems.append(f"{name} must be at least {MIN_SECRET_LENGTH} characters")
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        problems.append("DATABASE_URL is not set")
    if not config.get("REDIS_URL"):
        problems.append("REDIS_URL is not set")
    if not (config.get("CELERY") or {}).get("broker_url"):
        problems.append("RABBITMQ_URL is not set")
    return problems
