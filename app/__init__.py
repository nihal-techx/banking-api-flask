from flask_openapi3 import Info, OpenAPI

from app import models  # noqa: F401  (registers models with SQLAlchemy/Alembic)
from app.api import register_blueprints
from app.config import Config
from app.errors import (
    register_error_handlers,
    register_jwt_error_handlers,
    register_jwt_revocation,
    validation_error_response,
)
from app.extensions import db, jwt, migrate, redis_ext

SECURITY_SCHEMES = {"jwt": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}


def create_app(config_object=None):
    app = OpenAPI(
        __name__,
        info=Info(title="Banking API", version="0.1.0"),
        security_schemes=SECURITY_SCHEMES,
        validation_error_callback=validation_error_response,
    )
    app.config.from_object(config_object or Config)
    db.init_app(app)
    migrate.init_app(app, db)
    redis_ext.init_app(app)
    jwt.init_app(app)
    register_error_handlers(app)
    register_jwt_error_handlers(jwt)
    register_jwt_revocation(jwt)
    register_blueprints(app)
    return app