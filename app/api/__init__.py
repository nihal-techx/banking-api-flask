from app.api import accounts, auth, health, history, transfers


def register_blueprints(app):
    app.register_blueprint(health.bp)
    app.register_api(auth.bp)
    app.register_api(accounts.bp)
    app.register_api(transfers.bp)
    app.register_api(history.bp)
