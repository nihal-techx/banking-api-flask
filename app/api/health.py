from flask import Blueprint, jsonify
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db, redis_ext

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
        redis_ext.client.ping()
    except (SQLAlchemyError, RedisError):
        return jsonify(status="unavailable"), 503
    return jsonify(status="ready")
