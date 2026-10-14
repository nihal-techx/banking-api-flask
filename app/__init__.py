from flask import Flask

from app import models  # noqa: F401  (registers models with SQLAlchemy/Alembic)
from app.api import register_blueprints
from app.config import Config
from app.extensions import db, migrate


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    db.init_app(app)
    migrate.init_app(app, db)
    register_blueprints(app)
    return app