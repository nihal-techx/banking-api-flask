import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY", "dev-only-jwt-secret-change-me-32-bytes-min"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    LEDGER_LOCK_TIMEOUT_MS = 3000
    IDEMPOTENCY_KEY_REQUIRED = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL")
    RABBITMQ_URL = os.getenv("RABBITMQ_URL")
    CELERY = {
        "broker_url": os.getenv("RABBITMQ_URL"),
        "task_ignore_result": True,
        "broker_connection_retry_on_startup": True,
    }


class TestingConfig(Config):
    TESTING = True
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