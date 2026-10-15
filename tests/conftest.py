import pytest

from app import create_app
from app.config import TestingConfig
from app.extensions import db, redis_ext


@pytest.fixture(scope="session")
def app():
    app = create_app(TestingConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture(autouse=True)
def clean_db(app):
    yield
    with app.app_context():
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
    redis_ext.client.flushdb()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def signup(client):
    """Register + log in a user; returns ready-to-use auth headers."""

    def _signup(username):
        creds = {
            "email": f"{username}@example.com",
            "username": username,
            "password": "s3cret-pass-1",
        }
        assert client.post("/auth/register", json=creds).status_code == 201
        login = client.post(
            "/auth/login", json={"email": creds["email"], "password": creds["password"]}
        )
        return {"Authorization": f"Bearer {login.get_json()['access_token']}"}

    return _signup


@pytest.fixture
def run_concurrently(app):
    """Run callables in parallel threads, each with its own app context (own DB session).
    workers=None releases all jobs at once through a barrier, to maximize overlap.
    Returns a list of ("ok", result) or ("error", exception)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    def _run(jobs, workers=None):
        barrier = threading.Barrier(len(jobs)) if workers is None else None

        def wrap(job):
            def runner():
                with app.app_context():
                    if barrier is not None:
                        barrier.wait(timeout=10)
                    try:
                        return ("ok", job())
                    except Exception as exc:
                        return ("error", exc)

            return runner

        with ThreadPoolExecutor(max_workers=workers or len(jobs)) as pool:
            futures = [pool.submit(wrap(job)) for job in jobs]
            return [future.result(timeout=60) for future in futures]

    return _run