from flask_openapi3 import Info, OpenAPI

from app import models  # noqa: F401  (registers models with SQLAlchemy/Alembic)
from app.api import register_blueprints
from app.config import Config
from app.errors import register_error_handlers, validation_error_response
from app.extensions import db, migrate


def create_app(config_object=None):
    app = OpenAPI(
        __name__,
        info=Info(title="Banking API", version="0.1.0"),
        validation_error_callback=validation_error_response,
    )
    app.config.from_object(config_object or Config)
    db.init_app(app)
    migrate.init_app(app, db)
    register_error_handlers(app)
    register_blueprints(app)
    return app