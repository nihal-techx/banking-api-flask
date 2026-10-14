from app.api import health


def register_blueprints(app):
    app.register_blueprint(health.bp)
