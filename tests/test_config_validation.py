import pytest

from app import create_app
from app.config import TestingConfig, validate_production_config

STRONG = "x" * 40


def prod_config(**overrides):
    config = {
        "SECRET_KEY": STRONG,
        "JWT_SECRET_KEY": STRONG + "y",
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://u:p@db/app",
        "REDIS_URL": "redis://redis:6379/0",
        "CELERY": {"broker_url": "amqp://guest:guest@mq//"},
    }
    config.update(overrides)
    return config


def test_strong_production_config_has_no_problems():
    assert validate_production_config(prod_config()) == []


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"SECRET_KEY": "dev-secret-change-me"}, "SECRET_KEY"),
        ({"JWT_SECRET_KEY": "dev-only-jwt-secret-change-me-32-bytes-min"}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": "too-short"}, "JWT_SECRET_KEY"),
        ({"SQLALCHEMY_DATABASE_URI": None}, "DATABASE_URL"),
        ({"REDIS_URL": ""}, "REDIS_URL"),
        ({"CELERY": {"broker_url": None}}, "RABBITMQ_URL"),
    ],
)
def test_unsafe_production_config_is_flagged(overrides, expected):
    problems = validate_production_config(prod_config(**overrides))
    assert any(problem.startswith(expected) for problem in problems)


def test_create_app_refuses_unsafe_production_config_without_echoing_secrets():
    class UnsafeProduction(TestingConfig):
        APP_ENV = "production"

    with pytest.raises(RuntimeError, match="unsafe production configuration") as excinfo:
        create_app(UnsafeProduction)

    assert "dev-secret-change-me" not in str(excinfo.value)
    assert "dev-only-jwt-secret" not in str(excinfo.value)
