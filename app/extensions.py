import redis
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()


class RedisExtension:
    client: redis.Redis | None = None

    def init_app(self, app):
        self.client = redis.Redis.from_url(app.config["REDIS_URL"], decode_responses=True)


redis_ext = RedisExtension()
