from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError
from app.extensions import db
from app.models import User
from app.security import hash_password


def register_user(email: str, username: str, password: str) -> User:
    user = User(email=email, username=username, password_hash=hash_password(password))
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError("Email or username already registered")
    return user