from flask import Flask

from app.api import register_blueprints
from app.config import Config


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    register_blueprints(app)
    return app
