from flask_openapi3 import Info, OpenAPI

from app import models, tasks  # noqa: F401  (register models and Celery tasks)
from app.api import register_blueprints
from app.api.docs import API_DESCRIPTION
from app.celery_app import init_celery
from app.cli import register_cli
from app.config import Config, validate_production_config
from app.error_handlers import register_unexpected_error_handler
from app.errors import (
    register_error_handlers,
    register_jwt_error_handlers,
    register_jwt_revocation,
    validation_error_response,
)
from app.extensions import db, jwt, migrate, redis_ext
from app.logging_config import configure_logging
from app.request_context import register_request_hooks

SECURITY_SCHEMES = {"jwt": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}


def create_app(config_object=None):
    app = OpenAPI(
        __name__,
        info=Info(title="Banking API", version="1.0.0", description=API_DESCRIPTION),
        security_schemes=SECURITY_SCHEMES,
        validation_error_callback=validation_error_response,
    )
    app.config.from_object(config_object or Config)

    if app.config["APP_ENV"] == "production":
        problems = validate_production_config(app.config)
        if problems:
            raise RuntimeError(
                "Refusing to start with an unsafe production configuration: " + "; ".join(problems)
            )

    configure_logging(app)
    db.init_app(app)
    migrate.init_app(app, db)
    redis_ext.init_app(app)
    jwt.init_app(app)
    init_celery(app)
    register_request_hooks(app)
    register_error_handlers(app)
    register_unexpected_error_handler(app)
    register_jwt_error_handlers(jwt)
    register_jwt_revocation(jwt)
    register_blueprints(app)
    register_cli(app)
    return app
