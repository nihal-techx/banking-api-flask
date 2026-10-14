from app.api import auth, health


def register_blueprints(app):
    app.register_blueprint(health.bp)
    app.register_api(auth.bp)