import redis
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db, redis_ext


def test_ready_is_503_when_redis_is_down(client, monkeypatch):
    def down():
        raise redis.ConnectionError("redis is down")

    monkeypatch.setattr(redis_ext.client, "ping", down)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable"}


def test_ready_is_503_when_the_database_is_down(client, monkeypatch):
    def down(*args, **kwargs):
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr(db.session, "execute", down)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable"}